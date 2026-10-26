"""Every shell of the scan, measured.

The scan is stitched from pieces, and the stitch tore in places, so the
body arrives as tens of thousands of loose shells: some of them are the
ear cup, most of them are a single triangle of dust.  A round of cleanup
starts from knowing what there is, so this writes out the size, the
outline and the place of every shell.

Usage:
  blender -b -P scripts/probe_yxz_shell_table.py -- --glb <glb> --out <json>
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
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


def measure(group, uv_layer):
    faces = set(group)
    boundary = [e for e in {e for f in faces for e in f.edges}
                if len([f for f in e.link_faces if f in faces]) == 1]
    lengths = [e.calc_length() for e in boundary]
    verts = {v for f in faces for v in f.verts}
    uv = [(l[uv_layer].uv.x, l[uv_layer].uv.y) for f in faces for l in f.loops]
    return {
        "faces": len(faces),
        "verts": len(verts),
        "boundaryEdges": len(boundary),
        "boundaryLength": round(sum(lengths), 6),
        "meanEdge": round(sum(lengths) / max(len(lengths), 1), 6),
        "area": round(float(sum(f.calc_area() for f in faces)), 7),
        "uv": [round(min(u for u, v in uv), 4), round(min(v for u, v in uv), 4),
               round(max(u for u, v in uv), 4), round(max(v for u, v in uv), 4)],
    }


def main():
    source = value_after("--glb")
    out = value_after("--out")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    rows = []
    for number, group in enumerate(shells(bm)):
        stats = measure(group, uv_layer)
        points = np.array([[v.co.x, v.co.y, v.co.z] for f in group
                           for v in f.verts])
        low = points.min(axis=0)
        high = points.max(axis=0)
        stats["shell"] = number
        stats["low"] = [round(float(v), 4) for v in low]
        stats["high"] = [round(float(v), 4) for v in high]
        stats["centre"] = [round(float(v), 4) for v in (low + high) / 2]
        stats["density"] = round(stats["boundaryEdges"] / max(stats["faces"], 1), 4)
        rows.append(stats)

    payload = {"source": source, "shells": rows}
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    total = sum(row["faces"] for row in rows)
    print("YXZ_SHELL_TABLE " + json.dumps({
        "shells": len(rows), "faces": total,
        "bySize": {
            "one": sum(1 for r in rows if r["faces"] == 1),
            "under10": sum(1 for r in rows if r["faces"] < 10),
            "under100": sum(1 for r in rows if r["faces"] < 100),
            "over1000": sum(1 for r in rows if r["faces"] > 1000),
        },
    }))


main()


