from tracekit.replay import comp_to_ui, marker, paint_geometry, presented_frame, run_session


def build_frame_layouts(source, base_policy):
    result = {}
    by_session = {}
    for row in source['paint_frames']:
        by_session.setdefault(row['session'], []).append(row)
    for sid, frames in by_session.items():
        capture_times = [
            (row['frame_id'], comp_to_ui(source, sid, float(row['comp_us'])))
            for row in frames
        ]
        snapshots = run_session(
            sid, source, base_policy, keep_state=True, capture_times=capture_times
        )
        for row in frames:
            result[(sid, row['frame_id'])] = snapshots[row['frame_id']]
    return result


def painted_checkpoint(source, sid, checkpoint, surface_policy, paint_policy, frame_layouts):
    frame_id = presented_frame(source, sid, checkpoint['ui_ms'], surface_policy)
    frame_state = frame_layouts[(sid, frame_id)]
    tree_rev, relative_y = paint_geometry(source, sid, frame_id, paint_policy)
    visual_scroll = frame_state['scroll_top_css'] - relative_y
    if paint_policy['sign'] == 'add':
        visual_scroll = frame_state['scroll_top_css'] + relative_y
    visual_scroll += frame_state.get('cache_origin_adjust_css', 0.0)
    visual_scroll += frame_state.get('scheduler_scroll_adjust_css', 0.0)
    item, offset = marker(frame_state['order'], frame_state['heights'], visual_scroll)
    return {
        'scroll_top_css': round(checkpoint['scroll_top_css'], 4),
        'paint_frame': frame_id,
        'tree_revision': tree_rev,
        'visual_scroll_css': round(visual_scroll, 4),
        'marker_item': item,
        'marker_offset_css': round(offset, 4),
    }
