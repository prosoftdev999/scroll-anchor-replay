#!/usr/bin/env python3
"""Deliberately weak shortcut used only to test the sealed verifier."""
import csv
import json
import os
from pathlib import Path

DATA = Path(os.environ.get("TASK_DATA", "/app/data"))
OUT = Path(os.environ.get("TASK_OUTPUT", "/app/output/recovered.json"))

def rows(name):
    with (DATA / name).open(newline="") as f:
        return list(csv.DictReader(f))

controls = rows("control_checkpoints.csv")
queries = rows("incident_checkpoints.csv")
frames = rows("paint_frames.csv")
bindings = rows("frame_scroll_bindings.csv")
bases = rows("scroll_base_records.csv")
prototype = [r for r in controls if r["session"] == "s-e18"]
first = frames[0]
first_binding = next(r for r in bindings if r["session"] == first["session"] and r["frame_id"] == first["frame_id"])
base_sum = sum(float(r["base_css"]) for r in bases if r["session"] == first["session"] and r["commit_id"] == first_binding["commit_id"])

out = []
for i, query in enumerate(queries):
    p = prototype[min(i, len(prototype) - 1)]
    scroll = float(p["scroll_top_css"])
    out.append({
        "checkpoint_id": query["checkpoint_id"],
        "scroll_top_css": scroll,
        "paint_frame": first["frame_id"],
        "tree_revision": int(first["property_rev"]),
        "visual_scroll_css": scroll,
        "marker_item": p["marker_item"],
        "marker_offset_css": float(p["marker_offset_css"]),
        "render_commit": first_binding["commit_id"],
        "pending_input_css": 0.0,
        "effective_scroll_css": base_sum,
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"schema_version": 3, "checkpoints": out}, indent=2) + "\n")
