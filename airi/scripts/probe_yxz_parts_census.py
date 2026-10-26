"""A census of the pieces the model is made of.

 * The scan arrives as a couple of hundred separate blobs, and the head
 * is only a few of them: the helmet, the visor, the ear cups, the
 * wreck of the old halo.  They have to be told apart before any of
 * them can be taken away, and a list of sizes says very little: a
 * torn flap and a panel of the helmet are the same size and the same
 * shape of thing.  This prints, for every piece, where it is and what
 * rectangle of the atlas it owns, which is enough to say what it is.
 *
 * Usage:
 *  blender -b -P scripts/probe_yxz_parts_census.py -- --glb <glb> \
 *    [--min-faces 1] [--out <json>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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
    min_faces = int(value_after("--min-faces", "1"))
    out = value_after("--out")

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
        if len(group) < min_faces:
            continue
        points = [vert.co for face in group for vert in face.verts]
        if not points:
            continue
        area = sum(face.calc_area() for face in group)
        rect = rect_of(group, uv_layer)
        records.append({
            "shell": number,
            "faces": len(group),
            "area": round(area, 6),
            "low": [round(min(p[i] for p in points), 4) for i in range(3)],
            "high": [round(max(p[i] for p in points), 4) for i in range(3)],
            "rect": [round(float(v), 4) for v in rect],
        })
    records.sort(key=lambda r: -r["faces"])

    report = {"glb": glb, "totalShells": len(groups), "pieces": records}
    text = json.dumps(report)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    print("YXZ_CENSUS " + json.dumps({
        "totalShells": len(groups),
        "listed": len(records),
        "pieces": records[:60],
    }))


main()
