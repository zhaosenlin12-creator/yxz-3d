"""The shape of the helmet shell, face by face.

The shell of the helmet is one welded piece that holds both the smooth
dome and the drift of torn flakes that stand over it.  The two cannot be
told apart by which piece they belong to, because they are the same
piece, so they have to be told apart by their shape.

A face of the dome lies on a sphere, so the middle of the head is
straight out of its plane and the face stands on the sphere at one
radius.  A face of a torn sheet that has been welded onto the dome
stands at some other radius, and it does not lie on the sphere.

So this prints the two numbers for every face of the shell -- how far
out from the middle of the head it stands, and how far its own normal
is from pointing straight out -- as a table, so the flakes can be seen
in the numbers rather than guessed at.

Usage:
  blender -b -P scripts/probe_yxz_shell_profile.py -- \
    --glb <glb> --out <json> [--island 572] \
    [--centre 0.038,-0.001,0.094]
"""

from __future__ import annotations

import json
import math
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
    out = Path(value_after("--out"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()

    groups = islands(bm)
    main_island = max(range(len(groups)), key=lambda i: len(groups[i]))

    radius_edges = [0.270 + 0.002 * i for i in range(30)]
    angle_edges = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

    def bucket(edges, value):
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]:
                return index
        return len(edges) - 2

    table = {}
    for number, group in enumerate(groups):
        counts = [[0] * (len(angle_edges) - 1) for _ in range(len(radius_edges) - 1)]
        outside = 0
        for face in group:
            middle = face.calc_center_median()
            offset = middle - centre
            distance = offset.length
            if distance > 0.42 or distance < 0.10:
                outside += 1
                continue
            radial = offset.normalized()
            angle = math.degrees(math.acos(max(-1.0, min(1.0, face.normal.dot(radial)))))
            counts[bucket(radius_edges, distance)][bucket(angle_edges, angle)] += 1
        table[number] = {
            "faces": len(group),
            "outside": outside,
            "counts": counts,
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "glb": str(glb),
        "mainIsland": main_island,
        "radiusEdges": radius_edges,
        "angleEdges": angle_edges,
        "islands": {str(k): v for k, v in table.items() if v["faces"] >= 20},
    }), encoding="utf-8")
    print("YXZ_SHELL_PROFILE %s islands=%d" % (out, len(table)))
    bm.free()


if __name__ == "__main__":
    main()
