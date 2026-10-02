#!/usr/bin/env python3
"""Recover retained virtual-list measurement cache state from LevelDB log fragments."""
import csv
import json
import struct
from pathlib import Path

BLOCK_SIZE = 32768
FULL, FIRST, MIDDLE, LAST = 1, 2, 3, 4
POLY = 0x82F63B78

_CRC_TABLE = []
for i in range(256):
    c = i
    for _ in range(8):
        c = (c >> 1) ^ POLY if c & 1 else c >> 1
    _CRC_TABLE.append(c & 0xFFFFFFFF)


def _crc32c(data: bytes):
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC_TABLE[(c ^ b) & 0xFF] ^ (c >> 8)
    return (c ^ 0xFFFFFFFF) & 0xFFFFFFFF


def _unmask(masked):
    rot = (masked - 0xA282EAD8) & 0xFFFFFFFF
    return ((rot >> 17) | ((rot << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _read_varint(buf, pos):
    value = 0
    shift = 0
    while pos < len(buf) and shift <= 28:
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7
    raise ValueError('invalid varint32')


def _logical_records(path: Path):
    raw = path.read_bytes()
    pos = 0
    assembling = bytearray()
    in_fragment = False
    while pos + 7 <= len(raw):
        block_off = pos % BLOCK_SIZE
        remaining = BLOCK_SIZE - block_off
        if remaining < 7:
            pos += remaining
            assembling.clear()
            in_fragment = False
            continue
        masked, length, rec_type = struct.unpack_from('<IHB', raw, pos)
        if masked == 0 and length == 0 and rec_type == 0:
            pos += remaining
            assembling.clear()
            in_fragment = False
            continue
        end = pos + 7 + length
        if end > len(raw) or length > remaining - 7:
            break  # torn physical record at crash tail
        frag = raw[pos + 7:end]
        if _crc32c(bytes([rec_type]) + frag) != _unmask(masked):
            # Invalid physical fragment cannot contribute to a logical record.
            assembling.clear()
            in_fragment = False
            pos = end
            continue
        if rec_type == FULL:
            assembling.clear()
            in_fragment = False
            yield frag
        elif rec_type == FIRST:
            assembling = bytearray(frag)
            in_fragment = True
        elif rec_type == MIDDLE:
            if in_fragment:
                assembling.extend(frag)
        elif rec_type == LAST:
            if in_fragment:
                assembling.extend(frag)
                yield bytes(assembling)
            assembling.clear()
            in_fragment = False
        pos = end


def _writebatch_entries(payload):
    if len(payload) < 12:
        raise ValueError('short WriteBatch')
    seq, count = struct.unpack_from('<QI', payload, 0)
    pos = 12
    entries = []
    for i in range(count):
        if pos >= len(payload):
            raise ValueError('truncated WriteBatch')
        tag = payload[pos]
        pos += 1
        klen, pos = _read_varint(payload, pos)
        if pos + klen > len(payload):
            raise ValueError('truncated WriteBatch key')
        key = payload[pos:pos + klen].decode('utf-8')
        pos += klen
        if tag == 1:
            vlen, pos = _read_varint(payload, pos)
            if pos + vlen > len(payload):
                raise ValueError('truncated WriteBatch value')
            value = payload[pos:pos + vlen].decode('utf-8')
            pos += vlen
            entries.append((seq + i, key, value))
        elif tag == 0:
            entries.append((seq + i, key, None))
        else:
            raise ValueError(f'unknown WriteBatch tag {tag}')
    if pos != len(payload):
        raise ValueError('trailing bytes in WriteBatch')
    return entries


def recover_kv(data: Path):
    with (data / 'cache_log_manifest.csv').open(newline='') as f:
        manifest = sorted(csv.DictReader(f), key=lambda r: int(r['capture_order']))
    latest = {}
    for row in manifest:
        for logical in _logical_records(data / row['file_name']):
            for seq, key, value in _writebatch_entries(logical):
                previous = latest.get(key)
                if previous is None or seq > previous[0]:
                    latest[key] = (seq, value)
    return {k: v for k, (_, v) in latest.items() if v is not None}


def _token_map(data: Path):
    rows = []
    with (data / 'cache_token_lifetimes.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            rows.append({
                'token': r['cache_token'],
                'first': int(r['first_generation_seq']),
                'last': int(r['last_generation_seq']),
                'item': r['item_id'],
            })
    return rows


def _resolve_token(lifetimes, token, generation_seq):
    matches = [
        r for r in lifetimes
        if r['token'] == token and r['first'] <= generation_seq <= r['last']
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f'cache token {token} has {len(matches)} logical identities at generation {generation_seq}'
        )
    return matches[0]['item']


def recover_frame_overlays(data: Path):
    kv = recover_kv(data)
    metas = {}
    patches = {}
    for key, value in kv.items():
        if key.startswith('meta/'):
            generation = key.split('/', 1)[1]
            metas[generation] = json.loads(value)
        elif key.startswith('patch/'):
            _, generation, token = key.split('/', 2)
            patches.setdefault(generation, {})[token] = json.loads(value)

    lifetimes = _token_map(data)
    memo = {}
    active = set()

    def state(generation):
        if generation in memo:
            heights, origin = memo[generation]
            return dict(heights), origin
        if generation in active:
            raise RuntimeError('retained-cache generation cycle')
        if generation not in metas:
            raise RuntimeError(f'missing retained-cache metadata for {generation}')
        active.add(generation)
        meta = metas[generation]
        gen_seq = int(meta['generation_seq'])
        parent = meta['parent']
        if parent:
            heights, origin = state(parent)
        else:
            heights, origin = {}, 0.0
        for token, patch in patches.get(generation, {}).items():
            item = _resolve_token(lifetimes, token, gen_seq)
            if patch['op'] == 'set':
                heights[item] = float(patch['height_css'])
            elif patch['op'] == 'clear':
                heights.pop(item, None)
            else:
                raise RuntimeError(f"unknown retained-cache patch op {patch['op']}")
        origin += float(meta['origin_delta_css'])
        active.remove(generation)
        memo[generation] = (dict(heights), origin)
        return dict(heights), origin

    with (data / 'frame_cache_bindings.csv').open(newline='') as f:
        bindings = list(csv.DictReader(f))
    result = {}
    for b in bindings:
        heights, origin = state(b['cache_generation'])
        result[(b['session'], b['frame_id'])] = {
            'height_overrides': heights,
            'origin_adjust_css': origin,
            'cache_generation': b['cache_generation'],
        }
    return result
