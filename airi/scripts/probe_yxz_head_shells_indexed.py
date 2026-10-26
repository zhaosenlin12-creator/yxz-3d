"""The loose pieces of the head, listed with the index they are given by
the shell numbering.

`render_yxz_isolate.py` numbers the shells by the first face of each
one, so the index that appears in a rendering is the index that has to
be used to take a piece away.  The list has to be produced with the
same numbering, or the two do not talk to each other.

Usage:
  blender -b -P scripts/probe_yxz_head_shells_indexed.py -- \
    --glb <glb> [--z 0.24] [--out <json>]
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


def shells(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
    bm.faces.ensure_lookup_table()
    groups = []
    unvisited = set(bm.faces)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        groups.append(group)
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def main():
    source = value_after("--glb")
    floor = float(value_after("--z", "0.24"))
    out = value_after("--out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    rows = []
    for number, group in enumerate(shells(bm)):
        coords = []
        area = 0.0
        for face in group:
            area += face.calc_area()
            for vertex in face.verts:
                coords.append(list(vertex.co))
        if not coords:
            continue
        points = np.array(coords)
        low = points.min(axis=0)
        high = points.max(axis=0)
        if high[2] <= floor:
            continue
        rows.append({
            "index": number,
            "faces": len(group),
            "area": round(area, 6),
            "low": [round(float(v), 4) for v in low],
            "high": [round(float(v), 4) for v in high],
        })
    rows.sort(key=lambda row: -row["faces"])
    payload = {"glb": source, "floor": floor, "shells": rows}
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
    print("YXZ_HEAD_SHELLS " + json.dumps({
        "count": len(rows),
        "top": rows[:24],
    }))


main()
