#!/usr/bin/env python3
import csv
import json
import os
from itertools import product
from pathlib import Path

from .journal import recover_overlay

DATA = Path(os.environ.get('TASK_DATA', '/app/data'))
MARKER_Y = 88.0


def read_csv(name):
    with (DATA / name).open(newline='') as f:
        return list(csv.DictReader(f))


def load():
    sessions = {r['session']: r for r in read_csv('sessions.csv')}
    heights = {}
    for r in read_csv('row_catalog.csv'):
        heights.setdefault(r['session'], {})[r['item_id']] = float(r['initial_height_css'])
    orders = {}
    with (DATA / 'orders.jsonl').open() as f:
        for line in f:
            r = json.loads(line)
            orders.setdefault(r['session'], {})[int(r['generation'])] = r['items']

    # The CSV scroll exporter is complete for healthy sessions.  The incident's
    # crash journal contains committed rows that were not flushed into that export.
    overlay = recover_overlay(
        DATA / 'scroll_journal.rbuf',
        DATA / 'broker_journal.rbuf',
        read_csv('broker_clock_sync.csv'),
        read_csv('paint_frames.csv'),
    )
    frame_scroll_bindings = read_csv('frame_scroll_bindings.csv')
    binding_by_key = {(r['session'], r['frame_id']): r for r in frame_scroll_bindings}
    for r in overlay['binding']:
        binding_by_key[(r['session'], r['frame_id'])] = r
    frame_scroll_bindings = list(binding_by_key.values())
    scroll_reconciliations = read_csv('scroll_reconciliations.csv') + overlay['reconcile']
    scroll_acks = read_csv('scroll_ack_records.csv') + overlay['ack']
    scroll_bases = read_csv('scroll_base_records.csv') + overlay['base']

    return {
        'sessions': sessions,
        'heights': heights,
        'orders': orders,
        'mounts': read_csv('mount_log.csv'),
        'ui': read_csv('ui_events.csv'),
        'comp': read_csv('compositor_events.csv'),
        'resize': read_csv('resize_entries.csv'),
        'sync': read_csv('clock_sync.csv'),
        'controls': read_csv('control_checkpoints.csv'),
        'requested': read_csv('incident_checkpoints.csv'),
        'paint_controls': read_csv('paint_control_checkpoints.csv'),
        'paint_frames': read_csv('paint_frames.csv'),
        'node_lifetimes': read_csv('node_lifetimes.csv'),
        'layer_bindings': read_csv('layer_bindings.csv'),
        'property_patches': read_csv('property_patches.csv'),
        'scale_table': {r['scale_token']: float(r['device_px_per_css_px']) for r in read_csv('scale_table.csv')},
        'display_sync': read_csv('display_sync.csv'),
        'surface_instances': read_csv('surface_instances.csv'),
        'surface_submissions': read_csv('surface_submissions.csv'),
        'surface_activations': read_csv('surface_activations.csv'),
        'surface_links': read_csv('surface_links.csv'),
        'render_bindings': read_csv('render_bindings.csv'),
        'presentations': read_csv('presentations.csv'),
        'presentation_controls': read_csv('presentation_control_checkpoints.csv'),
        'input_sync': read_csv('input_clock_sync.csv'),
        'input_devices': read_csv('input_devices.csv'),
        'input_scales': {(r['session'], r['scale_token']): float(r['device_px_per_css_px']) for r in read_csv('input_scale_table.csv')},
        'scroll_nodes': read_csv('scroll_node_lifetimes.csv'),
        'scroll_reconciliations': scroll_reconciliations,
        'scroll_acks': scroll_acks,
        'scroll_bases': scroll_bases,
        'frame_scroll_bindings': frame_scroll_bindings,
        'input_packets': read_csv('input_packets.csv'),
        'scroll_controls': read_csv('scroll_control_frames.csv'),
    }


def prefix(order, heights, item):
    total = 0.0
    for row in order:
        if row == item:
            return total
        total += heights[row]
    raise KeyError(item)


def marker(order, heights, scroll):
    top = 0.0
    for item in order:
        h = heights[item]
        screen_top = top - scroll
        if screen_top <= MARKER_Y < screen_top + h:
            return item, MARKER_Y - screen_top
        top += h
    raise RuntimeError('marker fell outside the logical list')


def fallback(old_order, new_order, anchor, mode):
    if anchor in new_order:
        return anchor
    i = old_order.index(anchor)
    directions = (range(i - 1, -1, -1), range(i + 1, len(old_order)))
    if mode == 'successor':
        directions = directions[::-1]
    for indices in directions:
        for j in indices:
            if old_order[j] in new_order:
                return old_order[j]
    raise RuntimeError('layout has no surviving row')


def affine_fit(rows, sid, x_name, y_name):
    pts = [(float(r[x_name]), float(r[y_name])) for r in rows if r['session'] == sid]
    xb = sum(x for x, _ in pts) / len(pts)
    yb = sum(y for _, y in pts) / len(pts)
    slope = sum((x - xb) * (y - yb) for x, y in pts) / sum((x - xb) ** 2 for x, _ in pts)
    return yb - slope * xb, slope


def clock_fit(source, sid):
    return affine_fit(source['sync'], sid, 'ui_ms', 'comp_us')


def display_fit(source, sid):
    return affine_fit(source['display_sync'], sid, 'ui_ms', 'display_us')


def comp_to_ui(source, sid, comp_us):
    intercept, slope = clock_fit(source, sid)
    return (comp_us - intercept) / slope


def input_fit(source, sid):
    return affine_fit(source['input_sync'], sid, 'input_us', 'comp_us')


def input_to_comp(source, sid, input_us):
    intercept, slope = input_fit(source, sid)
    return intercept + slope * input_us


def scroll_node_at(source, sid, handle, comp_us):
    rows = [
        r for r in source['scroll_nodes']
        if r['session'] == sid
        and r['node_handle'] == handle
        and float(r['first_comp_us']) <= comp_us <= float(r['last_comp_us'])
    ]
    if len(rows) != 1:
        raise RuntimeError(f'{handle} has {len(rows)} active scroll-node instances at {comp_us}')
    return rows[0]


def scroll_node_by_instance(source, sid, instance_id):
    rows = [
        r for r in source['scroll_nodes']
        if r['session'] == sid and r['instance_id'] == instance_id
    ]
    if len(rows) != 1:
        raise RuntimeError(f'scroll node {instance_id} is not unique')
    return rows[0]


def scroll_chain(source, sid, list_instance, viewport_instance):
    chain = []
    current = list_instance
    visited = set()
    while current != viewport_instance:
        if current in visited:
            raise RuntimeError('scroll tree cycle')
        visited.add(current)
        chain.append(current)
        parent = scroll_node_by_instance(source, sid, current)['parent_instance_id']
        if not parent:
            raise RuntimeError('list scroll node is not descended from the viewport node')
        current = parent
    return chain


def decoded_input_events(source, sid, frame_comp_us):
    devices = {
        (r['session'], r['device_token']): r
        for r in source['input_devices']
    }
    rows = [
        r for r in source['input_packets']
        if r['session'] == sid
        and input_to_comp(source, sid, float(r['input_us'])) <= frame_comp_us + 1e-6
    ]
    rows.sort(key=lambda r: int(r['input_seq']))
    gestures = {}
    decoded = []
    for r in rows:
        seq = int(r['input_seq'])
        event_comp = input_to_comp(source, sid, float(r['input_us']))
        device = devices[(sid, r['device_token'])]
        scale = source['input_scales'][(sid, device['scale_token'])]
        sample_css = float(r['sample_y_device_px']) / scale
        gid = r['gesture_id']
        phase = r['phase']
        if phase == 'begin':
            node = scroll_node_at(source, sid, r['hit_handle'], event_comp)
            gestures[gid] = {
                'instance_id': node['instance_id'],
                'previous_sample_css': sample_css,
                'alive': True,
            }
            decoded.append((seq, r['device_token'], phase, node['instance_id'], 0.0))
            continue

        state = gestures.get(gid)
        if state is None:
            raise RuntimeError(f'input gesture {gid} has no begin packet')
        node = scroll_node_by_instance(source, sid, state['instance_id'])
        if event_comp > float(node['last_comp_us']) + 1e-6:
            state['alive'] = False
        if device['sample_mode'] == 'cumulative':
            delta_css = sample_css - state['previous_sample_css']
        elif device['sample_mode'] == 'incremental':
            delta_css = sample_css
        else:
            raise RuntimeError(f"unknown input sample mode {device['sample_mode']}")
        state['previous_sample_css'] = sample_css
        instance_id = state['instance_id'] if state['alive'] else None
        decoded.append((seq, r['device_token'], phase, instance_id, delta_css))
        if phase in ('end', 'cancel'):
            state['alive'] = False
    return decoded


def apply_scroll_delta(source, sid, offsets, instance_id, delta_css):
    current = instance_id
    remaining = delta_css
    visited = set()
    while current and abs(remaining) > 1e-12:
        if current in visited:
            raise RuntimeError('scroll tree cycle while applying input')
        visited.add(current)
        if current not in offsets:
            # The latched node is not part of this commit's active tree.
            return
        node = scroll_node_by_instance(source, sid, current)
        lo = float(node['min_css'])
        hi = float(node['max_css'])
        before = offsets[current]
        after = min(hi, max(lo, before + remaining))
        offsets[current] = after
        remaining -= after - before
        current = node['parent_instance_id']


def scroll_base_state(source, sid, commit_id, memo=None):
    if memo is None:
        memo = {}
    key = (sid, commit_id)
    if key in memo:
        return dict(memo[key])
    reconciliations = [
        r for r in source['scroll_reconciliations']
        if r['session'] == sid and r['commit_id'] == commit_id
    ]
    if len(reconciliations) != 1:
        raise RuntimeError(f'commit {commit_id} is not unique')
    parent = reconciliations[0]['parent_commit_id']
    state = scroll_base_state(source, sid, parent, memo) if parent else {}
    for r in source['scroll_bases']:
        if r['session'] == sid and r['commit_id'] == commit_id:
            state[r['instance_id']] = float(r['base_css'])
    memo[key] = dict(state)
    return state


def frame_scroll_state(source, sid, frame_id):
    frames = [
        r for r in source['paint_frames']
        if r['session'] == sid and r['frame_id'] == frame_id
    ]
    if len(frames) != 1:
        raise RuntimeError(f'frame {frame_id} is not unique')
    frame_comp = float(frames[0]['comp_us'])
    bindings = [
        r for r in source['frame_scroll_bindings']
        if r['session'] == sid and r['frame_id'] == frame_id
    ]
    if len(bindings) != 1:
        raise RuntimeError(f'frame {frame_id} has ambiguous scroll binding')
    binding = bindings[0]
    reconciliations = [
        r for r in source['scroll_reconciliations']
        if r['session'] == sid and r['commit_id'] == binding['commit_id']
    ]
    if len(reconciliations) != 1:
        raise RuntimeError(f"commit {binding['commit_id']} is not unique")
    reconciliation = reconciliations[0]
    if float(reconciliation['applied_comp_us']) > frame_comp:
        raise RuntimeError('frame references a scroll commit that had not applied yet')
    ack_rows = [
        r for r in source['scroll_acks']
        if r['session'] == sid and r['ack_set_id'] == reconciliation['ack_set_id']
    ]
    ack_by_device = {r['device_token']: int(r['ack_input_seq']) for r in ack_rows}
    expected_devices = {r['device_token'] for r in source['input_devices'] if r['session'] == sid}
    if set(ack_by_device) != expected_devices:
        raise RuntimeError('scroll reconciliation does not contain one watermark per input device')

    list_instance = scroll_node_at(source, sid, binding['list_handle'], frame_comp)['instance_id']
    viewport_instance = scroll_node_at(source, sid, binding['viewport_handle'], frame_comp)['instance_id']
    chain = scroll_chain(source, sid, list_instance, viewport_instance)
    base = scroll_base_state(source, sid, binding['commit_id'])
    if any(instance_id not in base for instance_id in chain):
        raise RuntimeError('scroll commit does not contain the displayed frame chain')
    offsets = dict(base)
    for seq, device_token, phase, instance_id, delta_css in decoded_input_events(source, sid, frame_comp):
        if phase == 'begin' or seq <= ack_by_device[device_token] or instance_id is None:
            continue
        apply_scroll_delta(source, sid, offsets, instance_id, delta_css)

    base_sum = sum(base[instance_id] for instance_id in chain)
    effective_sum = sum(offsets[instance_id] for instance_id in chain)
    return {
        'render_commit': binding['commit_id'],
        'pending_input_css': round(effective_sum - base_sum, 4),
        'effective_scroll_css': round(effective_sum, 4),
    }


def snapshot(order, heights, scroll, ui_ms, keep_state):
    item, offset = marker(order, heights, scroll)
    row = {
        'scroll_top_css': round(scroll, 4),
        'marker_item': item,
        'marker_offset_css': round(offset, 4),
        'ui_ms': float(ui_ms),
    }
    if keep_state:
        row['order'] = list(order)
        row['heights'] = dict(heights)
    return row


def run_session(sid, source, policy, keep_state=False, capture_times=None):
    sessions = source['sessions']
    orders = source['orders']
    order = list(orders[sid][0])
    heights = dict(source['heights'][sid])
    scroll = float(sessions[sid]['initial_scroll_top_css'])
    generation = 0
    active_request = None
    anchor, _ = marker(order, heights, scroll)

    slot_map = {
        (int(r['generation']), r['slot']): r['item_id']
        for r in source['mounts'] if r['session'] == sid
    }
    batches = {}
    for r in source['resize']:
        if r['session'] == sid:
            batches.setdefault(r['batch_id'], []).append(r)

    intercept, slope = clock_fit(source, sid)
    events = []
    for e in source['ui']:
        if e['session'] == sid:
            events.append((float(e['ui_ms']), 0, e))
    for e in source['comp']:
        if e['session'] != sid:
            continue
        if policy['clock'] == 'affine':
            t = (float(e['comp_us']) - intercept) / slope
        else:
            t = float(e['comp_us']) / 1000.0
        events.append((t, 1, e))
    for label, t in capture_times or []:
        events.append((float(t), 2, {'kind': '__capture', 'ref': label}))
    events.sort(key=lambda x: (x[0], x[1]))

    result = {}
    for t, _, e in events:
        kind = e['kind']
        if kind == 'user_scroll':
            scroll = float(e['arg'])
            anchor, _ = marker(order, heights, scroll)
        elif kind == 'program_begin':
            arg = json.loads(e['arg'])
            scroll = prefix(order, heights, arg['item_id']) - float(arg['align_y_css'])
            active_request = e['ref']
        elif kind == 'program_settle':
            if active_request == e['ref']:
                active_request = None
                anchor, _ = marker(order, heights, scroll)
        elif kind == 'layout':
            new_generation = int(e['ref'][1:])
            new_order = list(orders[sid][new_generation])
            if active_request and policy['program_resize'] == 'suppress':
                order = new_order
                generation = new_generation
            else:
                keep = fallback(order, new_order, anchor, policy['removed_anchor'])
                screen_top = prefix(order, heights, keep) - scroll
                order = new_order
                generation = new_generation
                scroll = prefix(order, heights, keep) - screen_top
                anchor = keep
        elif kind == 'resize_delivery':
            entries = sorted(batches[e['ref']], key=lambda r: int(r['obs_seq']))
            chosen = {}
            for r in entries:
                bind_generation = int(r['capture_generation']) if policy['slot_binding'] == 'capture' else generation
                item = slot_map.get((bind_generation, r['slot']))
                if item is None:
                    continue
                if policy['duplicate'] == 'first':
                    chosen.setdefault(item, r)
                else:
                    chosen[item] = r
            before = prefix(order, heights, anchor) if anchor in order else 0.0
            for item, r in chosen.items():
                heights[item] = float(r['height_device_px']) / float(r['frame_scale'])
            if not (active_request and policy['program_resize'] == 'suppress') and anchor in order:
                scroll += prefix(order, heights, anchor) - before
        elif kind in ('checkpoint', '__capture'):
            result[e['ref']] = snapshot(order, heights, scroll, t, keep_state)
    return result


def surface_instance(source, sid, handle, comp_us, mode):
    rows = [
        r for r in source['surface_instances']
        if r['session'] == sid and r['surface_handle'] == handle
    ]
    if mode == 'interval':
        rows = [
            r for r in rows
            if float(r['first_comp_us']) <= comp_us <= float(r['last_comp_us'])
        ]
        if len(rows) != 1:
            raise RuntimeError(f'{handle} has {len(rows)} active surface instances')
        return rows[0]['instance_id']
    if mode == 'first':
        return min(rows, key=lambda r: float(r['first_comp_us']))['instance_id']
    if mode == 'last':
        return max(rows, key=lambda r: float(r['first_comp_us']))['instance_id']
    raise ValueError(mode)


def surface_frame_at(source, sid, handle, comp_us, basis, lifetime, activation_map):
    instance_id = surface_instance(source, sid, handle, comp_us, lifetime)
    candidates = []
    for r in source['surface_submissions']:
        if r['session'] != sid or r['surface_handle'] != handle or r['instance_id'] != instance_id:
            continue
        if basis == 'activation':
            t = activation_map.get((sid, r['frame_token']))
            if t is None:
                continue
        else:
            t = float(r['submitted_comp_us'])
        if t <= comp_us:
            candidates.append((t, int(r['submit_seq']), r))
    if not candidates:
        raise RuntimeError(f'no surface frame for {handle} at {comp_us}')
    return max(candidates, key=lambda x: (x[0], x[1]))


def presented_frame(source, sid, checkpoint_ui_ms, policy):
    if policy['clock'] == 'affine':
        d0, ds = display_fit(source, sid)
        checkpoint_display = d0 + ds * checkpoint_ui_ms
    else:
        checkpoint_display = checkpoint_ui_ms * 1000.0

    rows = [
        r for r in source['presentations']
        if r['session'] == sid and float(r['display_us']) <= checkpoint_display
    ]
    if not rows:
        raise RuntimeError('no presentation before checkpoint')
    present = max(rows, key=lambda r: float(r['display_us']))

    if policy['clock'] == 'affine':
        d0, ds = display_fit(source, sid)
        present_ui = (float(present['display_us']) - d0) / ds
        c0, cs = clock_fit(source, sid)
        present_comp = c0 + cs * present_ui
    else:
        present_comp = float(present['display_us'])

    activation_map = {
        (r['session'], r['frame_token']): float(r['activated_comp_us'])
        for r in source['surface_activations']
    }
    _, _, frame = surface_frame_at(
        source, sid, present['root_handle'], present_comp, policy['root_basis'], policy['lifetime'], activation_map
    )
    root_activation = activation_map.get((sid, frame['frame_token']))
    root_submission = float(frame['submitted_comp_us'])
    render_map = {
        (r['session'], r['frame_token']): r['paint_frame']
        for r in source['render_bindings']
    }
    child_map = {
        (r['session'], r['parent_frame_token']): r['child_handle']
        for r in source['surface_links']
    }
    for _ in range(8):
        bound = render_map.get((sid, frame['frame_token']))
        if bound:
            return bound
        child = child_map.get((sid, frame['frame_token']))
        if not child:
            raise RuntimeError('wrapper surface has no child')
        cutoff = policy['cutoff']
        if cutoff == 'parent_activation':
            child_comp = activation_map.get((sid, frame['frame_token']))
            if child_comp is None:
                raise RuntimeError('selected surface frame never activated')
        elif cutoff == 'parent_submission':
            child_comp = float(frame['submitted_comp_us'])
        elif cutoff == 'root_activation':
            child_comp = root_activation
            if child_comp is None:
                raise RuntimeError('selected root frame never activated')
        elif cutoff == 'root_submission':
            child_comp = root_submission
        elif cutoff == 'presentation':
            child_comp = present_comp
        else:
            raise ValueError(cutoff)
        _, _, frame = surface_frame_at(
            source, sid, child, child_comp, policy['child_basis'], policy['lifetime'], activation_map
        )
    raise RuntimeError('surface tree is deeper than expected')


def lifetime_for_handle(source, sid, handle, frame_seq, mode):
    rows = [
        r for r in source['node_lifetimes']
        if r['session'] == sid and r['node_handle'] == handle
    ]
    if mode == 'interval':
        rows = [
            r for r in rows
            if int(r['first_frame_seq']) <= frame_seq <= int(r['last_frame_seq'])
        ]
        if len(rows) != 1:
            raise RuntimeError(f'{handle} has {len(rows)} active lifetimes at frame {frame_seq}')
        return rows[0]['lifetime_id']
    if mode == 'first':
        return min(rows, key=lambda r: int(r['first_frame_seq']))['lifetime_id']
    if mode == 'last':
        return max(rows, key=lambda r: int(r['first_frame_seq']))['lifetime_id']
    raise ValueError(mode)


def state_for_lifetime(source, sid, lifetime_id, property_rev, revision_mode, unit_mode):
    rows = [
        r for r in source['property_patches']
        if r['session'] == sid and r['lifetime_id'] == lifetime_id
    ]
    if revision_mode == 'asof':
        rows = [r for r in rows if int(r['property_rev']) <= property_rev]
    elif revision_mode != 'latest':
        raise ValueError(revision_mode)
    if not rows:
        raise RuntimeError(f'no state for {lifetime_id} at revision {property_rev}')
    row = max(rows, key=lambda r: int(r['property_rev']))
    local_y = float(row['translate_y_device_px'])
    if unit_mode == 'scaled':
        local_y /= source['scale_table'][row['scale_token']]
    elif unit_mode != 'raw':
        raise ValueError(unit_mode)
    return row['parent_lifetime_id'], local_y


def paint_geometry(source, sid, frame_id, policy):
    matches = [
        r for r in source['paint_frames']
        if r['session'] == sid and r['frame_id'] == frame_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f'frame {frame_id} is not unique')
    frame = matches[0]
    frame_seq = int(frame['frame_seq'])
    rev = int(frame['property_rev'])
    bindings = [
        r for r in source['layer_bindings']
        if r['session'] == sid and int(r['frame_seq']) == frame_seq
    ]
    if len(bindings) != 1:
        raise RuntimeError('paint frame has ambiguous layer binding')
    binding = bindings[0]
    viewport = lifetime_for_handle(source, sid, binding['viewport_handle'], frame_seq, policy['lifetime'])
    current = lifetime_for_handle(source, sid, binding['list_handle'], frame_seq, policy['lifetime'])

    relative_y = 0.0
    visited = set()
    while current != viewport:
        if current in visited:
            raise RuntimeError('property tree cycle')
        visited.add(current)
        parent, local_y = state_for_lifetime(
            source, sid, current, rev, policy['revision'], policy['units']
        )
        relative_y += local_y
        if policy['scope'] == 'local':
            break
        if not parent:
            raise RuntimeError('list node is not descended from viewport node')
        current = parent
    return rev, relative_y
