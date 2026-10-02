# Virtual-list trace format

These captures came from one browser release of a windowed issue list. Healthy sessions and the incident session use the same runtime behavior.

The support dashboard's horizontal marker is **88 CSS px below the viewport content-box top**. `marker_item` is the stable logical row intersecting that line. When this release performs layout compensation, the logical row intersecting the same 88 CSS px line is the anchor. `marker_offset_css` is the distance from the row's top edge to the marker, in CSS px.

## Main-thread and layout records

`sessions.csv`
: Session role and initial DOM `scrollTop`, in CSS px. Generation 0 uses the order in `orders.jsonl`, and row heights start from `row_catalog.csv`.

`row_catalog.csv`
: Stable logical row IDs and their initial cached heights, in CSS px.

`orders.jsonl`
: Complete logical row order for each render generation. A `layout` event makes its referenced generation current.

`mount_log.csv`
: Which logical row occupied each recycled DOM slot in a render generation. Slot names are local DOM identities and are reused.

`ui_events.csv`
: Main-thread events on the session's `ui_ms` monotonic clock.

- `user_scroll`: `arg` is the new DOM `scrollTop` in CSS px.
- `layout`: `ref` is a generation from `orders.jsonl`.
- `resize_delivery`: `ref` is a callback batch from `resize_entries.csv`.
- `program_begin`: `arg` contains the requested logical row and the requested row-top alignment coordinate, in CSS px.
- `checkpoint`: `ref` is the checkpoint ID.

`resize_entries.csv`
: ResizeObserver callback entries. `capture_generation` is the render generation at measurement time; `obs_seq` is callback entry order. `height_device_px` is the measured block size in device pixels, and `frame_scale` is the device-pixel scale recorded with that measurement.

`compositor_events.csv`
: Compositor-side events on the independent `comp_us` monotonic clock. `program_settle` records completion of the imperative scroll request named by `ref`.

`clock_sync.csv`
: Same-instant samples of `ui_ms` and `comp_us`. Each session's two clocks are stable over the capture but have different origins and rates.

`control_checkpoints.csv`
: Healthy layout-space observations from the same release. Values are CSS-pixel values.

## Renderer paint and property-tree records

`paint_frames.csv`
: Renderer compositor frame records. `frame_seq` is local to a session, `comp_us` is the compositor timestamp of the renderer state carried by the frame, and `property_rev` is the corresponding property-tree revision. A renderer frame can be queued, activated, and presented later through the surface pipeline.

`layer_bindings.csv`
: Viewport and list-layer node handles associated with each renderer frame.

`node_lifetimes.csv`
: Frame-bounded lifetimes for compositor node handles. A handle can be reused after a prior lifetime ends. Frame bounds are inclusive.

`property_patches.csv`
: Revisioned property-node records. Each record gives a lifetime's parent and local Y translation in device pixels under the named scale token.

`scale_table.csv`
: Device pixels per CSS pixel for property-node translation records.

`paint_control_checkpoints.csv`
: Healthy painted observations at ordinary UI checkpoints. These were captured from the same release as the incident.

## Surface aggregation and presentation records

`surface_instances.csv`
: Time-qualified surface-handle instances on the compositor clock. A surface handle can be reused; the recorded interval says which instance that handle names at a given compositor time.

`surface_submissions.csv`
: Surface-frame submissions. `frame_token` is local to the capture, `instance_id` names the receiving surface instance, and `submitted_comp_us` is the compositor submission time. Submission order alone does not imply that a frame became visible.

`surface_activations.csv`
: Activation times for surface frames that activated. Some submitted frames are superseded before activation and therefore have no row here.

`surface_links.csv`
: Child-surface references carried by wrapper surface frames. The record intentionally names the child surface handle rather than a renderer frame.

`render_bindings.csv`
: Correspondence between leaf surface-frame tokens and renderer `paint_frame` IDs.

`presentations.csv`
: Display presentations on the independent `display_us` clock. Each presentation records its root surface handle.

`display_sync.csv`
: Same-instant samples of `ui_ms` and `display_us` for each session.

`presentation_control_checkpoints.csv`
: Additional healthy presentation observations. They record the renderer frame that was actually visible at the listed UI time.

## Compositor input and scroll-tree records

`input_clock_sync.csv`
: Same-instant samples of the input router's `input_us` clock and the renderer compositor's `comp_us` clock. Each session has a stable affine relationship between these clocks.

`input_devices.csv` and `input_scale_table.csv`
: Device sampling mode and device-pixel scale. An `incremental` sample is a per-packet Y delta. A `cumulative` sample is Y displacement from the gesture's begin packet, so its per-packet delta is the difference from the preceding sample in that gesture. This sampling meaning does not reset when a renderer commit acknowledges earlier packets.

`input_packets.csv`
: Input-router gesture packets ordered by `input_seq`. A `begin` packet's `hit_handle` establishes the scroll-node latch for that gesture at that instant. Later `hit_handle` values are diagnostic hit-test observations and do not retarget an existing latch. `update` and `end` samples can carry displacement. A latch stops affecting the captured tree when its resolved node instance's lifetime ends.

`scroll_node_lifetimes.csv`
: Time-qualified scroll-node handles, instance IDs, parent links, and inclusive CSS-pixel offset bounds. Handles may be reused by later instances. When an input delta reaches a node bound, the unconsumed remainder passes to its parent. Remainder beyond the captured viewport is not represented in this trace.

`scroll_reconciliations.csv`
: Scroll-tree commits applied on the compositor clock. `parent_commit_id` names the base-state parent; a blank parent starts a new lineage. `ack_set_id` names the per-device acknowledgement watermarks that were folded into the commit.

`scroll_ack_records.csv`
: Per-device input watermarks for an acknowledgement set. A packet is already represented by the commit base only when its sequence is no greater than the watermark for that packet's own device. The two device streams can advance independently.

`scroll_base_records.csv`
: Sparse base-state replacements for a scroll-tree commit. A commit inherits its parent's base state and then replaces the listed instance offsets; root commits begin empty. Pending input is replayed from the resulting inherited state. A latched instance absent from that active commit state does not contribute to that commit's frame state.

`frame_scroll_bindings.csv`
: For each renderer frame, the scroll commit it carries and the list/viewport scroll-node handles that bound the relevant path. Resolve those handles at the renderer frame's `comp_us` timestamp. The viewport itself is the path terminator and is excluded from path sums.

`scroll_control_frames.csv`
: Healthy scroll-tree observations from the same release. `pending_input_css` is the difference between the final and base offset sums along the list-to-viewport path; `effective_scroll_css` is the final path sum. Only packets whose input timestamp maps no later than the renderer frame's `comp_us` can affect that frame.

`incident_checkpoints.csv`
: Checkpoints whose state must be reconstructed.

The DOM and display pipelines are allowed to be out of step. `scroll_top_css` is the DOM `scrollTop` at the incident checkpoint. The painted fields describe the renderer frame that was actually on screen at that checkpoint. If an older renderer frame is still being presented, its row order, measured heights, and property state are the historical state carried by that frame rather than the newer DOM state.

`visual_scroll_css` is the painted content offset seen at the support marker, expressed in CSS px. Positive local Y translation moves a node downward in its parent coordinate space.

Within one source clock, lower timestamps occur first. No shipped trace depends on a tie between distinct event sources.

## Incident crash journals

The renderer and browser crash rings were captured before their normal exporters finished flushing. `scroll_journal.rbuf` can therefore contain a newer scroll reconciliation for an incident renderer frame than the row in the CSV export, while `broker_journal.rbuf` records whether that candidate was actually installed by the browser. `broker_clock_sync.csv` relates the browser handoff clock to `comp_us`. The binary page, transaction, dictionary, and handoff rules are documented in `scroll_journal_format.md`.

For `s-z62`, use a broker-installed journal transaction in place of the CSV scroll binding for the same renderer frame. A valid journal transaction whose handoff was not installed at that frame time does not alter the displayed state. The existing CSV rows remain authoritative for frames with no installed journal replacement.

## Deferred virtualizer work

The incident renderer frames also carry deferred virtualizer measurement state. `scheduler_format.md` defines the cooperative work trace, the healthy calibration observations, and how a frame's committed scheduler state adjusts its historical row heights and painted origin. Those adjustments belong to the renderer frame; they do not rewrite the DOM `scrollTop` recorded at the checkpoint.

## Retained measurement cache

The embedded browser process also had a persisted virtualizer measurement cache. The ordinary exporter did not finish before the crash; the surviving LevelDB journal fragments, their manifest, token lifetimes, and renderer-frame bindings are in `000271.log`, `000272.log`, `cache_log_manifest.csv`, `cache_token_lifetimes.csv`, and `frame_cache_bindings.csv`. `cache_format.md` documents the application records and how a recovered cache generation contributes to a renderer frame.

## Speculative geometry history

Some incident renderer frames carry geometry from a speculative virtualizer branch that the ordinary exporter had not yet folded into its historical frame snapshot. The branch state is part of the renderer frame: it affects the frame's historical row heights and painted origin, but does not change the DOM `scrollTop` at the checkpoint.

`frame_geometry_refs.csv`
: The geometry handoff token carried by an incident renderer frame. Tokens are reusable identities rather than globally unique branch IDs.

`geometry_handoff_lifetimes.csv`
: Inclusive compositor-time lifetimes for each `(handoff_token, generation)`. Resolve a frame's handoff generation at that frame's `comp_us` timestamp. A token can name a different generation later in the same session.

`geometry_offers.csv`
: Renderer offers for a handoff generation. `offer_seq` is local to that generation. `head_commit` names the offered geometry head. An offer cannot affect a frame before both `offered_comp_us` and `install_barrier_comp_us` have passed.

`geometry_browser_events.csv`
: Browser decisions on the existing `broker_us` clock. `accept` adds the referenced offer to the active speculative set; `revoke` removes it. At a renderer-frame time, replay only browser events no later than that time after converting `comp_us` with `broker_clock_sync.csv`. An accepted offer participates only after both its renderer offer and `install_barrier_comp_us` have occurred. When more than one accepted offer is eligible, the displayed geometry is their deepest common committed prefix in `geometry_commits.csv`; this release does not expose branch-private deltas until all still-accepted branches contain them.

`geometry_commits.csv`
: Parent-linked geometry history. Commit ancestry defines the common committed prefix used by the browser when speculative branches coexist. The installed head inherits every ancestor from the root to that head, then applies each commit's deltas in `delta_seq` order. `height_delta_css` is additive. `origin_delta_css` is additive and contributes to the frame's painted scroll origin after the retained-cache and deferred-scheduler adjustments. A blank `item_alias` means the row carries no height change.

`geometry_alias_lifetimes.csv`
: Time-qualified logical identities for reusable `item_alias` values. Resolve an alias using the `commit_seq` of the commit that contains the delta. The inclusive ranges do not overlap for a given alias.

Within these geometry records, lower timestamps or lower sequence values occur first. The shipped capture contains no timestamp tie whose ordering changes a graded value.
