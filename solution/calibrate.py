import csv
from itertools import permutations
from pathlib import Path

from tracekit.replay import frame_scroll_state, presented_frame, run_session
from frame_model import painted_checkpoint
from tracekit.scheduler import simulate


def layout_mismatches(source, policy):
    by_session = {}
    for r in source['controls']:
        by_session.setdefault(r['session'], []).append(r)
    misses = 0
    for sid, rows in by_session.items():
        got = run_session(sid, source, policy)
        for r in rows:
            v = got[r['checkpoint_id']]
            if (
                v['marker_item'] != r['marker_item']
                or abs(v['scroll_top_css'] - float(r['scroll_top_css'])) > 0.005
                or abs(v['marker_offset_css'] - float(r['marker_offset_css'])) > 0.005
            ):
                misses += 1
    return misses


def presentation_mismatches(source, policy):
    ui_times = {
        (e['session'], e['ref']): float(e['ui_ms'])
        for e in source['ui'] if e['kind'] == 'checkpoint'
    }
    misses = 0
    for r in source['paint_controls']:
        try:
            got = presented_frame(
                source, r['session'], ui_times[(r['session'], r['checkpoint_id'])], policy
            )
        except Exception:
            misses += 1
            continue
        if got != r['paint_frame']:
            misses += 1
    for r in source['presentation_controls']:
        try:
            got = presented_frame(source, r['session'], float(r['ui_ms']), policy)
        except Exception:
            misses += 1
            continue
        if got != r['paint_frame']:
            misses += 1
    return misses


def paint_mismatches(source, base_policy, surface_policy, paint_policy, frame_layouts):
    by_session = {}
    for r in source['paint_controls']:
        by_session.setdefault(r['session'], []).append(r)
    misses = 0
    for sid, rows in by_session.items():
        layout = run_session(sid, source, base_policy, keep_state=True)
        for r in rows:
            try:
                got = painted_checkpoint(
                    source, sid, layout[r['checkpoint_id']], surface_policy, paint_policy, frame_layouts
                )
            except Exception:
                misses += 1
                continue
            if (
                got['paint_frame'] != r['paint_frame']
                or got['tree_revision'] != int(r['tree_revision'])
                or got['marker_item'] != r['marker_item']
                or abs(got['visual_scroll_css'] - float(r['visual_scroll_css'])) > 0.005
                or abs(got['marker_offset_css'] - float(r['marker_offset_css'])) > 0.005
            ):
                misses += 1
    return misses


def scroll_mismatches(source):
    misses = 0
    for r in source['scroll_controls']:
        try:
            got = frame_scroll_state(source, r['session'], r['frame_id'])
        except Exception:
            misses += 1
            continue
        if (
            got['render_commit'] != r['render_commit']
            or abs(got['pending_input_css'] - float(r['pending_input_css'])) > 0.005
            or abs(got['effective_scroll_css'] - float(r['effective_scroll_css'])) > 0.005
        ):
            misses += 1
    return misses


def _read_csv(data: Path, name: str):
    with (data / name).open(newline='') as f:
        return list(csv.DictReader(f))


def scheduler_overlays(data: Path):
    updates = _read_csv(data, 'deferred_updates.csv')
    slices = _read_csv(data, 'scheduler_slices.csv')
    controls = _read_csv(data, 'scheduler_controls.csv')
    updates_by_trace = {}
    slices_by_trace = {}
    controls_by_trace = {}
    for r in updates:
        updates_by_trace.setdefault(r['trace_id'], []).append(r)
    for r in slices:
        slices_by_trace.setdefault(r['trace_id'], []).append(r)
    for r in controls:
        controls_by_trace.setdefault(r['trace_id'], []).append(r)

    def controls_match(simulated, expected):
        for c in expected:
            m = simulated[c['slice_id']]
            if m['committed_count'] != int(c['committed_count']):
                return False
            if abs(m['height_sum_css'] - float(c['height_sum_css'])) > 1e-6:
                return False
            if abs(m['scroll_adjust_css'] - float(c['scroll_adjust_css'])) > 1e-6:
                return False
            if m['pending_units'] != int(c['pending_units']):
                return False
            if m['held_count'] != int(c['held_count']):
                return False
        return True

    lanes = ('ln-a7', 'ln-c2', 'ln-f9', 'ln-k4')
    survivors = []
    for order in permutations(lanes):
        for quantum in (8, 12, 16, 20, 24):
            for age_weight in (1, 2, 3):
                for resume_penalty in (0, 1, 2):
                    for group_bonus in (1, 2, 3):
                        for age_cap in (2, 3, 4):
                            for tie_break in ('oldest', 'shortest'):
                                for commit_mode in ('atomic', 'prefix'):
                                    policy = {
                                        'lane_order': order,
                                        'age_quantum': quantum,
                                        'age_weight': age_weight,
                                        'resume_penalty': resume_penalty,
                                        'group_bonus': group_bonus,
                                        'age_cap': age_cap,
                                        'tie_break': tie_break,
                                        'commit_mode': commit_mode,
                                    }
                                    good = True
                                    for trace_id, expected in controls_by_trace.items():
                                        got = simulate(
                                            updates_by_trace[trace_id],
                                            slices_by_trace[trace_id],
                                            policy,
                                        )
                                        if not controls_match(got, expected):
                                            good = False
                                            break
                                    if good:
                                        survivors.append(policy)
    if len(survivors) != 1:
        raise RuntimeError(f'scheduler controls identify {len(survivors)} profiles')
    policy = survivors[0]

    simulations = {
        trace_id: simulate(updates_by_trace[trace_id], slices_by_trace[trace_id], policy)
        for trace_id in {r['trace_id'] for r in _read_csv(data, 'frame_scheduler_bindings.csv')}
    }
    by_token = {
        (u['trace_id'], u['update_token']): u
        for rows in updates_by_trace.values() for u in rows
    }
    overlays = {}
    for b in _read_csv(data, 'frame_scheduler_bindings.csv'):
        state = simulations[b['trace_id']][b['slice_id']]
        heights = {}
        scroll_adjust = 0.0
        for token in state['committed_tokens']:
            u = by_token[(b['trace_id'], token)]
            if u['item_id']:
                heights[u['item_id']] = heights.get(u['item_id'], 0.0) + float(u['height_delta_css'])
            scroll_adjust += float(u['scroll_adjust_css'])
        overlays[(b['session'], b['frame_id'])] = {
            'height_deltas': heights,
            'scroll_adjust_css': scroll_adjust,
        }
    return overlays
