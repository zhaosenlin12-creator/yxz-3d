"""
 * Name the loose pieces of the shell that are still on screen.
 *
 * Two of them are obvious once the model is looked at closely and are
 * both still there: the scan's own halo came back as blades of a broken
 * ring, and the ring that replaced it is drawn above the head, so the
 * blades are left lying on the crown as a scatter of dark triangles; and
 * a sheet of the helmet's trim was folded back on itself and left
 * resting on the cheek, where it reads as a ragged white tongue.
 *
 * Both are separate shells of their own, so both can be found by
 * reachability, and both can be named by the rectangle of the atlas they
 * own -- the scan's packing gives every piece its own patch.
 *
 * This prints, for every shell that is not the body: how many faces it
 * has, where it sits, which patch of the atlas it uses, and what colour
 * that patch is.  The patch is what a removal script can key on.
 *
 * Usage: blender -b -P scripts/probe_yxz_strays.py -- --glb <glb>
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


def load_atlas():
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


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
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    atlas = load_atlas()
    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active
    groups = shells(bm)
    body_group = max(groups, key=len)
    index = {face: number for number, face in enumerate(body_group)}
    for number, group in enumerate(groups):
        if group is body_group:
            continue
        points = [vert.co for face in group for vert in face.verts]
        uvs = [
            (loop[uv_layer].uv.x, loop[uv_layer].uv.y)
            for face in group
            for loop in face.loops
        ]
        # Mean colour of the patch, so a navy blade and a white sheet can
        # be told apart without rendering anything.
        colour = None
        if atlas is not None:
            samples = []
            for u, v in uvs[::max(1, len(uvs) // 400)]:
                x = int(min(atlas.shape[1] - 1, max(0, u * atlas.shape[1])))
                y = int(min(atlas.shape[0] - 1, max(0, v * atlas.shape[0])))
                samples.append(atlas[y, x])
            colour = [round(float(c), 4) for c in np.mean(samples, axis=0)[:3]]
        record = {
            "id": number,
            "faces": len(group),
            "xyzLow": [round(float(min(p[i] for p in points)), 4) for i in range(3)],
            "xyzHigh": [round(float(max(p[i] for p in points)), 4) for i in range(3)],
            "uvLow": [round(float(min(u[0] for u in uvs)), 4), round(float(min(u[1] for u in uvs)), 4)],
            "uvHigh": [round(float(max(u[0] for u in uvs)), 4), round(float(max(u[1] for u in uvs)), 4)],
            "colour": colour,
        }
        print("YXZ_STRAY " + json.dumps(record))
    print("YXZ_STRAY_TOTAL %d" % (len(groups) - 1))
    bm.free()


main()
