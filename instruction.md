# Recover the virtual-list viewport state

Support captured a windowed issue list after users reported jumpy scrolling. The incident session lost its trustworthy viewport snapshots, but the raw layout, observer, scheduler, compositor telemetry, retained measurement-cache logs, and the two process crash journals survived. Healthy sessions from the same client release are in `/app/data` as well. Recover every checkpoint listed in `/app/data/incident_checkpoints.csv`. `/app/data/trace_format.md` is the capture-format reference for field meanings, clocks, units, compositor-node history, crash-journal precedence, and initialization. The layout, painted, scheduler, and scroll-tree control observations in `/app/data` were recorded from the same client behavior as the incident.

Write `/app/output/recovered.json` in this form:

```json
{
  "schema_version": 3,
  "checkpoints": [
    {
      "checkpoint_id": "...",
      "scroll_top_css": 0.0,
      "paint_frame": "...",
      "tree_revision": 0,
      "visual_scroll_css": 0.0,
      "marker_item": "...",
      "marker_offset_css": 0.0,
      "render_commit": "...",
      "pending_input_css": 0.0,
      "effective_scroll_css": 0.0
    }
  ]
}
```

The top-level object and each checkpoint object must contain exactly the fields shown. Include every requested checkpoint exactly once, in the same order as `incident_checkpoints.csv`, with no extra checkpoint rows. `scroll_top_css`, `visual_scroll_css`, `marker_offset_css`, `pending_input_css`, and `effective_scroll_css` are CSS-pixel values and are accepted within 0.02 px of the recovered state. `scroll_top_css` is the DOM value at the checkpoint. `paint_frame` is the renderer frame actually visible at that checkpoint, `tree_revision` is that frame's integer property-tree revision, and `marker_item` is the stable logical row ID intersecting the support marker in the displayed frame. A displayed frame may carry an older layout state than the current DOM state.

For that displayed renderer frame, `render_commit` is its scroll-tree reconciliation commit. `pending_input_css` is the unacknowledged compositor-input displacement remaining along the frame's list-to-viewport scroll path, and `effective_scroll_css` is the resulting scroll-path offset after that input is applied. Both sums exclude the viewport node itself.

You have 7200 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
