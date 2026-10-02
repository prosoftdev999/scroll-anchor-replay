# Scroll Anchor Replay

A frontend reconstruction challenge focused on recovering historical scroll position and anchor behavior while a browser page changes over time.

Modern pages frequently update content without a full navigation. Elements may be inserted, removed, resized, replaced, or moved while the user is reading a page. Without scroll anchoring, those changes can cause the visible content to jump unexpectedly.

Scroll Anchor Replay reconstructs the browser state required to determine how the viewport should behave across a sequence of historical updates.

## Overview

Scroll position is not determined only by the final DOM.

Correct behavior can depend on:

- the previously visible anchor
- DOM insertion and removal
- layout changes
- element resizing
- nested scroll containers
- viewport geometry
- asynchronous updates
- rendering and commit order
- historical user scroll state
- anchor eligibility
- retained logical identity

The project treats these pieces as one replay problem.

## Repository Structure

```text
scroll-anchor-replay/
├── cheat/
├── environment/
├── solution/
├── tests/
├── instruction.md
└── task.toml
```

### `instruction.md`

Defines the reconstruction problem, supplied evidence, replay semantics, and required output.

### `environment/`

Contains the reproducible runtime and task data.

### `solution/`

Contains the reference replay implementation.

### `tests/`

Contains the independent verifier.

### `task.toml`

Defines task metadata and execution configuration.

## Scroll Anchoring

Scroll anchoring attempts to preserve the user's visual position when layout changes occur.

Consider a viewport containing:

```text
-------------------------
older content
-------------------------
anchor element
-------------------------
visible content
-------------------------
```

If content is inserted above the anchor:

```text
-------------------------
new content
-------------------------
older content
-------------------------
anchor element
-------------------------
visible content
-------------------------
```

the document has become taller.

A naive implementation would leave the absolute scroll offset unchanged, causing the anchor to move downward on screen.

Scroll anchoring compensates for that change so the anchor remains at approximately the same viewport position.

## Historical Replay

The task is fundamentally stateful.

A simplified reconstruction pipeline is:

```text
initial DOM / viewport
          ↓
historical mutation
          ↓
layout update
          ↓
anchor selection
          ↓
scroll adjustment
          ↓
next mutation
          ↓
next layout
          ↓
updated anchor state
          ↓
final reconstructed result
```

Each step depends on state produced by earlier steps.

Using only the final DOM or final scroll offset may therefore produce an incorrect result.

## Anchor Identity

An anchor is more than a numeric coordinate.

The reconstruction may need to preserve the logical identity of the element that represented the user's visual position.

For example:

```text
item-42
```

might move from one DOM index to another after list updates.

An implementation that preserves only:

```text
list index = 12
```

may anchor to the wrong content after insertion or deletion.

Logical identity and current geometry must be considered separately.

## Layout Changes

Many updates can alter an anchor's position:

- content inserted above it
- content removed above it
- font or image loading
- element resizing
- CSS changes
- visibility changes
- nested-container updates
- responsive reflow

The resulting scroll compensation depends on the geometry before and after the layout change.

Conceptually:

```text
anchor_before = viewport-relative position before update
anchor_after  = viewport-relative position after update

scroll correction ≈ anchor_after - anchor_before
```

The actual task semantics in `instruction.md` are authoritative.

## Nested Scroll Containers

Not every scroll occurs on the document viewport.

A page can contain nested scrolling regions:

```text
window
 └── application
      ├── sidebar scroller
      └── content scroller
           └── anchor
```

The correct scroll state may depend on which container owns the anchor and which coordinate system is being updated.

## Asynchronous Updates

Frontend changes can be scheduled through several asynchronous mechanisms.

Examples include:

- event callbacks
- microtasks
- rendering commits
- animation frames
- deferred layout work
- asynchronous data arrival

Two updates containing the same mutations can produce different historical states if their execution order differs.

Replay must therefore preserve the relevant ordering semantics.

## User Scroll Intent

Programmatic scroll correction should not blindly override later user input.

Conceptually, a reconstruction may need to distinguish:

```text
captured anchor state
```

from:

```text
newer user scroll intent
```

If the user scrolls while asynchronous reconstruction is still pending, the newer intent may need to take precedence.

This is one reason historical replay is more reliable than copying a final `scrollTop` value.

## Logical vs Physical Position

A robust reconstruction distinguishes:

```text
logical anchor
```

from:

```text
physical pixel offset
```

Pixel coordinates may change when layout changes.

The logical content that the user was following can remain the same.

A good replay therefore preserves the correct semantic anchor and recomputes its current physical position.

## Common Failure Modes

Several simple approaches can produce plausible but incorrect results.

### Keeping a fixed absolute scroll offset

This fails when content above the viewport changes size.

### Using the final DOM only

The final tree does not reveal which anchor was active earlier.

### Anchoring by list index

Indexes can change after insertions, removals, and reordering.

### Ignoring layout timing

Geometry observed before layout completion can differ from the final committed geometry.

### Applying an old scroll correction after newer user input

A stale asynchronous update can incorrectly override the user's latest intent.

### Replaying records only by file order

Recorded order may not always equal semantic execution order.

## Reconstruction Pipeline

A full implementation can be viewed as:

```text
event evidence
      ↓
recover historical order
      ↓
replay DOM mutations
      ↓
recompute layout state
      ↓
resolve logical anchor
      ↓
measure anchor displacement
      ↓
apply scroll compensation
      ↓
preserve user intent
      ↓
emit reconstructed state
```

## Technical Areas

This project exercises:

- JavaScript
- browser behavior
- DOM reconstruction
- scroll anchoring
- viewport geometry
- nested scrolling
- frontend state replay
- event ordering
- asynchronous rendering
- logical identity tracking
- layout reconstruction
- browser debugging
- deterministic simulation

## Output

The solver produces the artifact specified by:

```text
instruction.md
```

For the authoritative:

- output path
- schema
- field names
- ordering
- coordinate conventions
- anchor semantics
- rounding rules

refer to the task instructions.

## Validation

A correct implementation should derive scroll state from historical evidence rather than from a hard-coded final coordinate.

Validation should cover cases such as:

```text
content inserted above an anchor
content removed above an anchor
anchor movement
anchor replacement
nested scrolling
layout changes
newer user scroll intent
```

when those situations are represented in the supplied task data.

## Goal

The goal of Scroll Anchor Replay is to reconstruct the viewport state a browser should have produced while a dynamically changing page was being used.

The central principle is:

> Preserve the user's logical viewing position, not merely an old pixel offset.

## License

No license is currently specified.
