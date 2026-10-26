"""List the pieces of the scan that sit above the crown of the head.

The old halo came back from the scan as a torn crescent lying across the
top of the head, and most of it is taken away by its patch of the atlas.
What is left is the handful of pieces that straddle the crown, and they
are the black confetti that sits over the helmet on screen.

This lists every piece of the model that reaches above the crown, with
the rectangle of the atlas it owns, so the ones that belong to the wreck
can be told from the ones that are the head.

Usage:
  blender -b -P scripts/probe_yxz_wreck.py -- --glb <glb> [--above 0.34]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh


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


def rect_of(group, uv_layer):
    us = []
    vs = []
    for face in group:
        for loop in face.loops:
            us.append(loop[uv_layer].uv.x)
            vs.append(loop[uv_layer].uv.y)
    if not us:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(us), min(vs), max(us), max(vs))


def main():
    glb = value_after("--glb")
    above = float(value_after("--above", "0.34"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active
    groups = shells(bm)

    records = []
    for number, group in enumerate(groups):
        points = [vert.co for face in group for vert in face.verts]
        if not points:
            continue
        low_z = min(p.z for p in points)
        high_z = max(p.z for p in points)
        if high_z < above:
            continue
        area = sum(face.calc_area() for face in group)
        rect = rect_of(group, uv_layer)
        records.append({
            "shell": number,
            "faces": len(group),
            "area": round(area, 6),
            "lowZ": round(float(low_z), 4),
            "highZ": round(float(high_z), 4),
            "rect": [round(float(v), 4) for v in rect],
            "patchArea": round((rect[2] - rect[0]) * (rect[3] - rect[1]), 5),
        })

    records.sort(key=lambda r: -r["faces"])
    print("YXZ_WRECK_PROBE " + json.dumps({
        "glb": glb,
        "shells": len(groups),
        "above": above,
        "count": len(records),
        "pieces": records[:80],
    }))


main()
