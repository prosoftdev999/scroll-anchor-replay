# Deferred virtualizer scheduler trace

The issue list does not apply every measurement correction to the painted tree as soon as the callback is observed. This client release batches low-priority virtualizer work through a small cooperative scheduler. The build-time scheduler profile was not written into the incident bundle, but the healthy calibration traces in `scheduler_controls.csv` were recorded from the same build.

`deferred_updates.csv`
: Work items queued by the virtualizer. `enqueue_ms` uses the UI clock. `lane_token` is an opaque scheduler lane. `cost_units` is the number of cooperative work units needed to finish the item. `after_token`, when present, means that item cannot run until the referenced item has finished. `group_token`, when present, links work that can be held at the commit boundary. For the incident trace, `item_id` names the logical row whose committed cached height changes by `height_delta_css`. `scroll_adjust_css` is the committed origin compensation paired with that work item; it changes painted content offset, not DOM `scrollTop`.

`scheduler_slices.csv`
: Cooperative work windows. At a slice, at most `budget_units` units can run. Eligibility is evaluated before every unit, so a partially processed item may be preempted between units. An item's age for a slice is `max(0, slice.ui_ms - enqueue_ms)`.

The scheduler score for an eligible item is:

`lane_rank + age_weight * min(age_cap, floor(age / age_quantum_ms)) + group_bonus_term - resume_penalty_term`

The four lane ranks are a permutation of `0, 2, 4, 6`. `group_bonus_term` is the build's group bonus when another unfinished, already-enqueued member of the same non-empty group exists, otherwise zero. `resume_penalty_term` is the build's resume penalty for a partially processed item, otherwise zero.

The shipped build came from this configuration matrix:

- `age_quantum_ms`: 8, 12, 16, 20, or 24
- `age_weight`: 1, 2, or 3
- `resume_penalty`: 0, 1, or 2
- `group_bonus`: 1, 2, or 3
- `age_cap`: 2, 3, or 4
- tie break: either oldest enqueue first, or shortest remaining work first (then oldest enqueue)
- group commit mode: either `atomic` or `prefix`

For `atomic`, members of a non-empty group become committed together only after every member of that group has finished. For `prefix`, finished members commit in enqueue order only through the first unfinished member. Ungrouped finished work commits at the end of the slice in either mode. A dependency only controls run eligibility; it does not change group commit behavior.

`scheduler_controls.csv`
: Healthy calibration observations after named slices. They record cumulative committed item count, cumulative signed height correction, cumulative origin compensation, unfinished work units, and the number of finished items still held by group-commit rules. These traces are independent of the issue-list sessions and exist only to recover the build profile.

`frame_scheduler_bindings.csv`
: Associates incident renderer frames with the scheduler slice whose committed virtualizer state the frame carries. Apply the cumulative committed incident work at that slice to the historical row heights carried by the frame, then add the cumulative committed `scroll_adjust_css` to the frame's painted content offset. The DOM checkpoint `scroll_top_css` is unchanged by this renderer-side historical reconstruction.
