"""Census of the body's connected shells, so a loose sheet can be named.

The scan arrives as a couple of hundred disconnected blobs.  The body is
the largest of them; the rest are the trim, the lenses, the lining of the
ear cups and a handful of sheets that were folded over and left lying on
the face.  Nothing about a loose sheet gives it away -- it is painted the
same white as the cheek it rests on, and it sits on the face rather than
beside it -- but the atlas does.  Every blob was given its own patch of
the texture when the scan was packed, so a blob that is loose owns a patch
to itself, well away from the patch the cheek uses.

So the census prints, for each shell, how big it is and which patch of the
atlas it owns.  A shell whose patch is a small rectangle of its own, on a
face, is the sheet; the rectangle is then what `remove_yxz_debris.py`
needs.

Usage:
  blender -b -P scripts/probe_yxz_islands.py -- --glb <glb> [--seed u,v]
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
    return groups


def uv_of(face, uv_layer):
    us = [loop[uv_layer].uv.x for loop in face.loops]
    vs = [loop[uv_layer].uv.y for loop in face.loops]
    return sum(us) / len(us), sum(vs) / len(vs)


def main() -> None:
    source = value_after("--glb")
    seed = value_after("--seed")
    seed_uv = None
    if seed:
        parts = seed.split(",")
        seed_uv = (float(parts[0]), float(parts[1]))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active

    rows = []
    for group in shells(bm):
        us, vs, pts = [], [], []
        for face in group:
            u, v = uv_of(face, uv_layer)
            us.append(u)
            vs.append(v)
            pts.append(list(face.calc_center_median()))
        pts = np.array(pts)
        rows.append({
            "faces": len(group),
            "uvLow": [round(min(us), 4), round(min(vs), 4)],
            "uvHigh": [round(max(us), 4), round(max(vs), 4)],
            "xyzLow": [round(float(x), 4) for x in pts.min(axis=0)],
            "xyzHigh": [round(float(x), 4) for x in pts.max(axis=0)],
        })

    # The largest shell is the character; the rest are what is being hunted.
    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_TOTAL " + json.dumps({"shells": len(rows), "seed": seed_uv}))

    for index, row in enumerate(rows[1:], start=1):
        if row["faces"] > 4000:
            continue
        hit = ""
        if seed_uv is not None:
            u0, v0 = row["uvLow"]
            u1, v1 = row["uvHigh"]
            if u0 <= seed_uv[0] <= u1 and v0 <= seed_uv[1] <= v1:
                hit = "  <== SEED"
        print("YXZ_ISLAND %d %s%s" % (
            index, json.dumps(row, sort_keys=True), hit))

    bm.free()


if __name__ == "__main__":
    main()
