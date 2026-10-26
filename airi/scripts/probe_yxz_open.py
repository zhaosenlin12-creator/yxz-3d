"""Every open run of the shell, measured.

`probe_yxz_holes.py` counts edges that have no face at all, which is a
different question from the one that matters here.  A scan is stitched
from pieces, and where two pieces were cut apart the edge between them
has a face on one side and nothing on the other: it is an *open
boundary*, and the surface stops there.  On screen that is a crack the
background shows through, and the outline pass inking it turns the crack
into a black line -- which is where the shattered-glass look comes from.

So this counts the edges with exactly one face, walks them into runs, and
writes down how big each run is and where it is.  A run of a few edges is
a nick; a run of hundreds around the crown is the tear to be closed.

Usage:
  blender -b -P scripts/probe_yxz_open.py -- --glb <glb> [--out <json>]
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


def open_runs(bm):
    """The runs of edges that have a face on only one side."""
    bm.faces.index_update()
    bm.edges.index_update()
    bm.verts.index_update()

    open_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    adjacency = {}
    for edge in open_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)

    unvisited = {edge.index: edge for edge in open_edges}
    runs = []
    while unvisited:
        seed = unvisited.pop(min(unvisited))
        run = [seed]
        stack = [seed]
        while stack:
            current = stack.pop()
            for vertex in current.verts:
                for other in vertex.link_edges:
                    if len(other.link_faces) != 1:
                        continue
                    if other.index in unvisited:
                        del unvisited[other.index]
                        run.append(other)
                        stack.append(other)
        runs.append(run)
    return runs


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
    for run in open_runs(bm):
        coords = []
        for edge in run:
            for vertex in edge.verts:
                coords.append(list(vertex.co))
        points = np.array(coords)
        low = points.min(axis=0)
        high = points.max(axis=0)
        length = 0.0
        for edge in run:
            length += (edge.verts[0].co - edge.verts[1].co).length
        rows.append({
            "edges": len(run),
            "length": round(float(length), 4),
            "span": round(float(max(high - low)), 4),
            "low": [round(float(v), 4) for v in low],
            "high": [round(float(v), 4) for v in high],
        })
    rows.sort(key=lambda row: -row["edges"])

    head = [row for row in rows
            if row["high"][2] > 0.18 and row["low"][2] > 0.05]
    payload = {
        "source": source,
        "faces": len(bm.faces),
        "verts": len(bm.verts),
        "openRuns": len(rows),
        "openEdges": sum(row["edges"] for row in rows),
        "headRuns": len(head),
        "headEdges": sum(row["edges"] for row in head),
        "rows": rows[:60],
        "headRows": head[:40],
    }
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
    print("YXZ_OPEN " + json.dumps({
        "faces": payload["faces"],
        "openRuns": payload["openRuns"],
        "openEdges": payload["openEdges"],
        "headRuns": payload["headRuns"],
        "headEdges": payload["headEdges"],
        "top": rows[:12],
        "headTop": head[:12],
    }))


main()
