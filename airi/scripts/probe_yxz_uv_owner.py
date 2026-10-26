"""Which piece of the model owns a given corner of the texture atlas.

The scan gives every piece of itself a rectangle of the atlas to itself,
so a detail in the design -- the star on the forehead -- belongs to
exactly one piece of geometry, and that piece can be found by looking
for the one whose rectangle covers the detail's texels.

Usage:
  blender -b -P scripts/probe_yxz_uv_owner.py -- \
    --glb <glb> --uv u,v [--radius 0.02] [--out <json>]
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
    u, v = [float(part) for part in value_after("--uv", "0,0").split(",")]
    radius = float(value_after("--radius", "0.02"))
    out = value_after("--out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    if bm.loops.layers.uv.active is None:
        raise RuntimeError("the mesh has no uv layer")
    uv_layer = bm.loops.layers.uv.active

    rows = []
    for number, group in enumerate(shells(bm)):
        us = []
        vs = []
        for face in group:
            for loop in face.loops:
                us.append(loop[uv_layer].uv.x)
                vs.append(loop[uv_layer].uv.y)
        rect = (min(us), min(vs), max(us), max(vs))
        if not (rect[0] - radius <= u <= rect[2] + radius
                and rect[1] - radius <= v <= rect[3] + radius):
            continue
        coords = []
        area = 0.0
        for face in group:
            area += face.calc_area()
            for vertex in face.verts:
                coords.append(list(vertex.co))
        points = np.array(coords)
        rows.append({
            "index": number,
            "faces": len(group),
            "area": round(area, 6),
            "rect": [round(value, 5) for value in rect],
            "low": [round(float(value), 4) for value in points.min(axis=0)],
            "high": [round(float(value), 4) for value in points.max(axis=0)],
        })
    rows.sort(key=lambda row: -row["faces"])
    payload = {"glb": source, "uv": [u, v], "owners": rows}
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
    print("YXZ_UV_OWNER " + json.dumps({"uv": [u, v], "owners": rows[:12]}))


main()
