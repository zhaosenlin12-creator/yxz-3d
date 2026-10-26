"""How many faces does each shell have?  A cross check between scripts."""

from __future__ import annotations

import sys

import bpy
import bmesh


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


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=value_after("--glb"))
body = max(
    (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
    key=lambda obj: len(obj.data.vertices),
)
bm = bmesh.new()
bm.from_mesh(body.data)
groups = shells(bm)
print("YXZ_SHELLS %d" % len(groups))
for number in [int(piece) for piece in value_after("--ids", "1,6287,6303,6346").split(",")]:
    if number < len(groups):
        print("  shell %d faces=%d" % (number, len(groups[number])))
    else:
        print("  shell %d out of range" % number)
