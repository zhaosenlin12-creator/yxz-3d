"""How far out from the middle of the head does the crown reach?

The design has a clear bubble over the helmet, and in the scan that
bubble is a skin of geometry standing clear of the white shell.  It
shattered, and what survives of it is a drift of shards lying across
the top of the head -- which is what the character reads as broken.

The helmet itself is very nearly a sphere, so the two are told apart by
how far out from the middle of the head they reach: the shell is at
about 0.289, the bubble's shards are out past that.

This lists the head's faces by the radius they reach, so the shell and
the bubble can be told apart by a number rather than by eye.

Usage:
  blender -b -P scripts/probe_yxz_crown_radius.py -- \
    --source <glb> [--centre 0.038,-0.001,0.094] [--min-z 0.16]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = Path(value_after("--source"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    min_z = float(value_after("--min-z", "0.16"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    # Faces grouped by how far out from the middle of the head they lie,
    # in bands of five thousandths.
    bands = {}
    for face in bm.faces:
        middle = face.calc_center_median()
        if middle.z < min_z:
            continue
        distance = (middle - centre).length
        key = round(distance / 0.005) * 0.005
        band = bands.setdefault(key, {"faces": 0})
        band["faces"] += 1

    # The shells, with the radius they reach.
    unvisited = set(bm.faces)
    shells = []
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
        shells.append(group)

    rows = []
    for number, group in enumerate(shells):
        points = [v.co for face in group for v in face.verts]
        if not points:
            continue
        if max(p.z for p in points) < min_z:
            continue
        radii = [(p - centre).length for p in points]
        rows.append({
            "shell": number,
            "faces": len(group),
            "rMin": round(min(radii), 4),
            "rMax": round(max(radii), 4),
            "zMax": round(max(p.z for p in points), 4),
        })
    rows.sort(key=lambda row: -row["rMax"])

    print("YXZ_CROWN_RADIUS " + json.dumps({
        "bands": {str(round(k, 3)): v["faces"] for k, v in sorted(bands.items())},
        "shells": len(rows),
        "beyond289": sum(1 for row in rows if row["rMax"] > 0.289),
        "beyond289Faces": sum(row["faces"] for row in rows if row["rMax"] > 0.289),
        "top": rows[:25],
    }))
    bm.free()


if __name__ == "__main__":
    main()
