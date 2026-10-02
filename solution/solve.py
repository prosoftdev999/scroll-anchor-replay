#!/usr/bin/env python3
import json
import os
import sys
from itertools import product
from pathlib import Path

# The reference intentionally uses the same agent-visible capture toolkit that is
# baked into /app. TASK_TOOLKIT exists only to make local clean-room validation easy.
sys.path.insert(0, os.environ.get('TASK_TOOLKIT', '/app'))

from tracekit.cache import recover_frame_overlays as recover_cache_overlays
from tracekit.replay import frame_scroll_state, load, run_session
from frame_model import build_frame_layouts, painted_checkpoint
from calibrate import (
    layout_mismatches,
    paint_mismatches,
    presentation_mismatches,
    scheduler_overlays,
    scroll_mismatches,
)
from geometry import recover_geometry_overlays

OUT = Path(os.environ.get('TASK_OUTPUT', '/app/output/recovered.json'))
DATA = Path(os.environ.get('TASK_DATA', '/app/data'))


def unique_profile(keys, options, mismatch_fn, label):
    survivors = []
    for values in product(*options):
        policy = dict(zip(keys, values))
        if mismatch_fn(policy) == 0:
            survivors.append(policy)
    if len(survivors) != 1:
        raise RuntimeError(f'{label} controls identify {len(survivors)} profiles')
    return survivors[0]


def main():
    source = load()

    base_policy = unique_profile(
        ['slot_binding', 'removed_anchor', 'program_resize', 'duplicate', 'clock'],
        [
            ['capture', 'delivery'],
            ['predecessor', 'successor'],
            ['suppress', 'compensate'],
            ['last', 'first'],
            ['affine', 'naive'],
        ],
        lambda p: layout_mismatches(source, p),
        'layout',
    )

    surface_policy = unique_profile(
        ['clock', 'root_basis', 'child_basis', 'lifetime', 'cutoff'],
        [
            ['affine', 'naive'],
            ['activation', 'submission'],
            ['activation', 'submission'],
            ['interval', 'first', 'last'],
            ['parent_activation', 'parent_submission', 'root_activation', 'root_submission', 'presentation'],
        ],
        lambda p: presentation_mismatches(source, p),
        'presentation',
    )

    frame_layouts = build_frame_layouts(source, base_policy)

    # Retained cache state is the historical base for the bound renderer frame.
    for key, overlay in recover_cache_overlays(DATA).items():
        state = dict(frame_layouts[key])
        state['heights'] = dict(state['heights'])
        state['heights'].update(overlay['height_overrides'])
        state['cache_origin_adjust_css'] = overlay['origin_adjust_css']
        frame_layouts[key] = state

    # Deferred scheduler commits are layered on top of that retained state.
    for key, overlay in scheduler_overlays(DATA).items():
        state = dict(frame_layouts[key])
        state['heights'] = dict(state['heights'])
        for item_id, delta in overlay['height_deltas'].items():
            state['heights'][item_id] += delta
        state['scheduler_scroll_adjust_css'] = overlay['scroll_adjust_css']
        frame_layouts[key] = state

    # Renderer geometry history is independently promoted by the browser.
    # Reconstruct the installed branch at each frame time, then replay its lineage.
    for key, overlay in recover_geometry_overlays(DATA, source['paint_frames']).items():
        state = dict(frame_layouts[key])
        state['heights'] = dict(state['heights'])
        for item_id, delta in overlay['height_deltas'].items():
            state['heights'][item_id] += delta
        state['scheduler_scroll_adjust_css'] = (
            state.get('scheduler_scroll_adjust_css', 0.0) + overlay['origin_adjust_css']
        )
        frame_layouts[key] = state

    paint_policy = unique_profile(
        ['lifetime', 'revision', 'scope', 'units', 'sign'],
        [
            ['interval', 'first', 'last'],
            ['asof', 'latest'],
            ['ancestry', 'local'],
            ['scaled', 'raw'],
            ['subtract', 'add'],
        ],
        lambda p: paint_mismatches(source, base_policy, surface_policy, p, frame_layouts),
        'paint',
    )

    if scroll_mismatches(source) != 0:
        raise RuntimeError('scroll controls do not reproduce')

    requested = source['requested']
    incident_sessions = {r['session'] for r in requested}
    if len(incident_sessions) != 1:
        raise RuntimeError('capture does not contain exactly one incident session')
    sid = next(iter(incident_sessions))
    layout = run_session(sid, source, base_policy, keep_state=True)

    checkpoints = []
    for request in requested:
        row = {'checkpoint_id': request['checkpoint_id']}
        row.update(
            painted_checkpoint(
                source,
                sid,
                layout[request['checkpoint_id']],
                surface_policy,
                paint_policy,
                frame_layouts,
            )
        )
        row.update(frame_scroll_state(source, sid, row['paint_frame']))
        checkpoints.append(row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({'schema_version': 3, 'checkpoints': checkpoints}, indent=2) + '\n')


if __name__ == '__main__':
    main()
