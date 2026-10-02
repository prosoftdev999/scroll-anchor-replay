#!/usr/bin/env python3
import hashlib
import json
import struct
import zlib
from pathlib import Path

PAGE_SIZE = 768
PAGE_HEADER = 20
FRAG_HEADER = 20
MAGIC = b"RBJ2"


def _canon(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


def decode_records(path: Path):
    """Recover logical JSON records from a crash ring without trusting physical page order."""
    data = path.read_bytes()
    if len(data) % PAGE_SIZE:
        raise RuntimeError(f"{path.name} is not page aligned")

    copies = {}
    for slot in range(len(data) // PAGE_SIZE):
        page = data[slot * PAGE_SIZE:(slot + 1) * PAGE_SIZE]
        magic, stored_slot, page_epoch, write_seq, used, flags = struct.unpack('<4sHHIHH', page[:16])
        page_crc, = struct.unpack('<I', page[16:20])
        if magic != MAGIC or stored_slot != slot or flags != 0 or used > PAGE_SIZE - PAGE_HEADER:
            continue
        payload = page[PAGE_HEADER:PAGE_HEADER + used]
        if zlib.crc32(page[:16] + payload) & 0xffffffff != page_crc:
            continue

        pos = 0
        while pos < len(payload):
            if pos + FRAG_HEADER > len(payload):
                raise RuntimeError("checksummed page ends in a partial fragment header")
            logical_seq, frag_index, frag_count, codec, copy_gen, frag_len, total_len, record_crc = struct.unpack(
                '<IHHBBHII', payload[pos:pos + FRAG_HEADER]
            )
            pos += FRAG_HEADER
            if frag_count == 0 or frag_index >= frag_count or codec not in (0, 1):
                raise RuntimeError("invalid fragment metadata on a checksummed page")
            if pos + frag_len > len(payload):
                raise RuntimeError("checksummed page ends in a partial fragment")
            frag = payload[pos:pos + frag_len]
            pos += frag_len
            key = (logical_seq, frag_index)
            rank = (copy_gen, page_epoch, write_seq, slot)
            item = (rank, frag_count, codec, total_len, record_crc, frag)
            if key not in copies or rank > copies[key][0]:
                copies[key] = item

    by_record = {}
    for (logical_seq, frag_index), item in copies.items():
        by_record.setdefault(logical_seq, {})[frag_index] = item

    out = []
    for logical_seq in sorted(by_record):
        frags = by_record[logical_seq]
        sample = next(iter(frags.values()))
        _, frag_count, codec, total_len, record_crc, _ = sample
        if set(frags) != set(range(frag_count)):
            continue
        metadata = {(v[1], v[2], v[3], v[4]) for v in frags.values()}
        if len(metadata) != 1:
            raise RuntimeError(f"record {logical_seq} has inconsistent fragments")
        encoded = b''.join(frags[i][5] for i in range(frag_count))
        if len(encoded) != total_len:
            continue
        try:
            raw = zlib.decompress(encoded) if codec == 1 else encoded
        except zlib.error:
            continue
        if zlib.crc32(raw) & 0xffffffff != record_crc:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append((logical_seq, obj))
    return out


def build_dictionary(records):
    maps = {}
    seen_reset = set()
    for _, obj in records:
        if obj.get('kind') == 'dict_reset':
            ep = int(obj['epoch'])
            if ep in seen_reset:
                raise RuntimeError(f"dictionary epoch {ep} resets twice")
            seen_reset.add(ep)
            maps.setdefault(ep, {})
        elif obj.get('kind') == 'dict':
            ep = int(obj['epoch'])
            if ep not in seen_reset:
                raise RuntimeError("dictionary entry precedes its reset")
            key = (obj['space'], int(obj['code']))
            prev = maps[ep].get(key)
            if prev is not None and prev != obj['value']:
                raise RuntimeError("conflicting dictionary entry")
            maps[ep][key] = obj['value']
    return maps


def resolve(maps, ep, space, code):
    try:
        return maps[int(ep)][(space, int(code))]
    except KeyError as e:
        raise RuntimeError(f"unresolved dictionary code {ep}:{space}:{code}") from e


def committed_transactions(records):
    """Validate begin/data/terminal boundaries and transaction digests."""
    maps = build_dictionary(records)
    tx = {}
    for seq, obj in records:
        kind = obj.get('kind')
        if kind in ('dict_reset', 'dict'):
            continue
        if 'epoch' not in obj or 'txn' not in obj:
            continue
        key = (int(obj['epoch']), int(obj['txn']))
        state = tx.setdefault(key, {'begin': None, 'data': [], 'terminal': []})
        if kind == 'txn_begin':
            state['begin'] = seq
            state['data'] = []
            state['terminal'] = []
        elif state['begin'] is not None and seq > state['begin']:
            if kind in ('txn_commit', 'txn_abort'):
                state['terminal'].append((seq, obj))
            else:
                state['data'].append((seq, obj))

    accepted = []
    for (ep, txn), state in tx.items():
        if state['begin'] is None or not state['terminal']:
            continue
        terminal_seq, terminal = max(state['terminal'], key=lambda x: x[0])
        if terminal.get('kind') != 'txn_commit':
            continue
        data = [(s, o) for s, o in state['data'] if s < terminal_seq]
        if int(terminal.get('count', -1)) != len(data):
            continue
        digest = hashlib.sha256(b''.join(_canon(o) for _, o in data)).hexdigest()
        if digest != terminal.get('sha256'):
            continue
        handoff = resolve(maps, ep, 'handoff', terminal['handoff'])
        accepted.append({
            'epoch': ep,
            'txn': txn,
            'begin_seq': state['begin'],
            'terminal_seq': terminal_seq,
            'handoff': handoff,
            'handoff_generation': int(terminal['handoff_generation']),
            'data': data,
            'maps': maps,
        })
    return accepted


def broker_events(path: Path):
    records = decode_records(path)
    maps = build_dictionary(records)
    out = []
    for seq, obj in records:
        if obj.get('kind') not in ('lease_open', 'accept', 'revoke'):
            continue
        ep = int(obj['epoch'])
        out.append({
            'seq': seq,
            'kind': obj['kind'],
            'handoff': resolve(maps, ep, 'handoff', obj['handoff']),
            'generation': int(obj['generation']),
            'broker_us': float(obj['broker_us']),
            'sink_epoch': int(obj['sink_epoch']),
        })
    return out


def _affine(rows, x_name, y_name):
    pts = [(float(r[x_name]), float(r[y_name])) for r in rows]
    xb = sum(x for x, _ in pts) / len(pts)
    yb = sum(y for _, y in pts) / len(pts)
    slope = sum((x - xb) * (y - yb) for x, y in pts) / sum((x - xb) ** 2 for x, _ in pts)
    return yb - slope * xb, slope


def installed_at(events, handoff, generation, broker_cutoff):
    relevant = [
        e for e in events
        if e['handoff'] == handoff and e['generation'] == generation and e['broker_us'] <= broker_cutoff + 1e-6
    ]
    if not relevant:
        return False
    latest = max(relevant, key=lambda e: (e['broker_us'], e['seq']))
    return latest['kind'] == 'accept'


def _decode_candidate(tx):
    maps = tx['maps']
    decoded = {'binding': [], 'reconcile': [], 'ack': [], 'base': []}
    for seq, obj in tx['data']:
        kind = obj.get('kind')
        if kind not in decoded:
            continue
        ep = int(obj['epoch'])
        session = resolve(maps, ep, 'session', obj['session'])
        version = int(obj.get('version', 1))
        if kind == 'binding':
            row = {
                'session': session,
                'frame_id': resolve(maps, ep, 'frame', obj['frame']),
                'commit_id': resolve(maps, ep, 'commit', obj['commit']),
                'list_handle': resolve(maps, ep, 'handle', obj['list_handle']),
                'viewport_handle': resolve(maps, ep, 'handle', obj['viewport_handle']),
            }
        elif kind == 'reconcile':
            row = {
                'session': session,
                'commit_id': resolve(maps, ep, 'commit', obj['commit']),
                'parent_commit_id': resolve(maps, ep, 'commit', obj['parent_commit']),
                'ui_ms': str(obj['ui_ms']),
                'applied_comp_us': str(obj['applied_comp_us']),
                'ack_set_id': resolve(maps, ep, 'ack', obj['ack_set']),
            }
        elif kind == 'ack':
            row = {
                'session': session,
                'ack_set_id': resolve(maps, ep, 'ack', obj['ack_set']),
                'device_token': resolve(maps, ep, 'device', obj['device']),
                'ack_input_seq': str(int(obj['ack_input_seq'])),
            }
        else:
            row = {
                'session': session,
                'commit_id': resolve(maps, ep, 'commit', obj['commit']),
                'instance_id': resolve(maps, ep, 'instance', obj['instance']),
                'base_css': str(obj['base_css']),
            }
        decoded[kind].append((version, seq, row))
    return decoded


def recover_overlay(scroll_path: Path, broker_path: Path, broker_sync_rows, paint_frames):
    renderer_records = decode_records(scroll_path)
    candidates = committed_transactions(renderer_records)
    events = broker_events(broker_path)
    b0, bs = _affine(broker_sync_rows, 'comp_us', 'broker_us')
    frame_comp = {(r['session'], r['frame_id']): float(r['comp_us']) for r in paint_frames}

    eligible = []
    for tx in candidates:
        decoded = _decode_candidate(tx)
        bindings = [x[2] for x in decoded['binding']]
        reconciles = [x[2] for x in decoded['reconcile']]
        if len(bindings) != 1 or len(reconciles) != 1:
            continue
        b = bindings[0]
        r = reconciles[0]
        key = (b['session'], b['frame_id'])
        if key not in frame_comp:
            continue
        cutoff_comp = frame_comp[key]
        if float(r['applied_comp_us']) > cutoff_comp + 1e-6:
            continue
        cutoff_broker = b0 + bs * cutoff_comp
        if installed_at(events, tx['handoff'], tx['handoff_generation'], cutoff_broker):
            eligible.append((tx, decoded))

    by_frame = {}
    for tx, decoded in eligible:
        binding = decoded['binding'][0][2]
        key = (binding['session'], binding['frame_id'])
        by_frame.setdefault(key, []).append((tx, decoded))

    # Every raw-journal frame must have one and only one broker-installed transaction.
    for key, rows in by_frame.items():
        if len(rows) != 1:
            raise RuntimeError(f"{key} has {len(rows)} broker-installed journal transactions")

    best = {'binding': {}, 'reconcile': {}, 'ack': {}, 'base': {}}
    for key in sorted(by_frame):
        tx, decoded = by_frame[key][0]
        for kind, items in decoded.items():
            for version, seq, row in items:
                if kind == 'binding':
                    rkey = (row['session'], row['frame_id'])
                elif kind == 'reconcile':
                    rkey = (row['session'], row['commit_id'])
                elif kind == 'ack':
                    rkey = (row['session'], row['ack_set_id'], row['device_token'])
                else:
                    rkey = (row['session'], row['commit_id'], row['instance_id'])
                rank = (version, seq)
                prev = best[kind].get(rkey)
                if prev is None or rank > prev[0]:
                    best[kind][rkey] = (rank, row)

    return {kind: [v[1] for _, v in sorted(items.items())] for kind, items in best.items()}
