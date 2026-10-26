"""What is standing clear of the head, and how far clear of it.

The clear bubble over the helmet has to come off the scan, and the test
for it is that it stands clear of the sphere the helmet is built on.  But
the same test catches the raised hand, which is also clear of the head
and also in the upper half of the figure, and taking the hand off is a
worse thing than a glassy dome.

So the islands in the band are measured and printed, and the rule is
written against what is actually there.

Usage:
  blender -b -P scripts/probe_yxz_bubble_islands.py -- \
    --glb <glb> [--centre 0.038,-0.001,0.094] [--low 0.28] [--high 0.46] \
    [--top 200]
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


def islands(bm):
    bm.faces.ensure_lookup_table()
    unvisited = set(bm.faces)
    groups = []
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


def main() -> None:
    glb = Path(value_after("--glb"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    low = float(value_after("--low", "0.28"))
    high = float(value_after("--high", "0.46"))
    top = int(value_after("--top", "200"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    rows = []
    for number, group in enumerate(islands(bm)):
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            continue
        radii = [(point - centre).length for point in points]
        r_min = min(radii)
        r_max = max(radii)
        if r_max < low or r_min > high:
            continue
        centre_of = Vector((0.0, 0.0, 0.0))
        for point in points:
            centre_of += point
        centre_of /= len(points)
        rows.append({
            "island": number,
            "faces": len(group),
            "rMin": round(r_min, 4),
            "rMax": round(r_max, 4),
            "spread": round(r_max - r_min, 4),
            "at": [round(v, 4) for v in centre_of],
        })

    rows.sort(key=lambda row: -row["faces"])
    print("YXZ_BUBBLE_ISLANDS " + json.dumps({
        "count": len(rows),
        "top": rows[:top],
    }))


if __name__ == "__main__":
    main()
