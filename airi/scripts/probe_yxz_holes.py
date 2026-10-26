"""Every tear in the shell, measured.

The repair script can close a tear, but it closes the wrong ones: the
crown of the helmet is torn open over a span of a quarter of a unit, and
capping that leaves a hedgehog of needles standing off the head.  So the
head is put out of the repair's reach, and with it every hairline crack
in the face -- and the cracks are what make the character read as
broken.

The two are told apart by the size of the run of boundary edges around
them, so this writes that size down for every tear in the model, and
where it is, so the two lists can be separated.

Usage:
  blender -b -P scripts/probe_yxz_holes.py -- --glb <glb> [--out <json>]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def boundary_loops(bm):
    """The runs of edges that have a face on only one side."""
    # The indices are what the runs are keyed by, and `ensure_lookup_table`
    # does not set them.
    bm.faces.index_update()
    bm.edges.index_update()
    bm.verts.index_update()
    used = set()
    for face in bm.faces:
        for edge in face.edges:
            used.add(edge.index)
    loops = []
    for edge in bm.edges:
        if edge.index in used:
            continue
        seen = set()
        stack = [edge]
        loop = []
        while stack:
            current = stack.pop()
            if current.index in seen:
                continue
            seen.add(current.index)
            loop.append(current)
            for vertex in current.verts:
                for other in vertex.link_edges:
                    if other.index in used or other.index in seen:
                        continue
                    stack.append(other)
        if loop:
            loops.append(loop)
    return loops


def main():
    source = value_after("--glb")
    out = value_after("--out")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    rows = []
    for loop in boundary_loops(bm):
        points = np.array([[c for vertex in edge.verts for c in vertex.co]
                           for edge in loop])
        low = points.min(axis=0)
        high = points.max(axis=0)
        rows.append({
            "edges": len(loop),
            "span": round(float(max(high - low)), 4),
            "low": [round(float(v), 3) for v in low],
            "high": [round(float(v), 3) for v in high],
        })
    rows.sort(key=lambda row: -row["edges"])
    payload = {"source": source, "loops": rows}
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    head = [row for row in rows if row["high"][2] > 0.18]
    print("YXZ_HOLES_PROBE " + json.dumps({
        "total": len(rows),
        "faces": len(bm.faces),
        "headLoops": len(head),
        "headSmall": sum(1 for row in head if row["edges"] <= 40),
        "headBig": sum(1 for row in head if row["edges"] > 40),
        "headSmallFaces": sum(row["edges"] for row in head if row["edges"] <= 40),
        "top20": rows[:20],
    }))


main()
