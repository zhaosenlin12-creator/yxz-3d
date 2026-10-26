"""List the separate shells of the welded YXZ body, and show where they are.

The scan arrives as a couple of hundred separate pieces, and the ones that
matter are the small ones: a scrap of the helmet trim torn loose and left
floating across the face reads as a broken shell, and it cannot be
repaired because there is nothing behind it to repair it against.

A shell is a set of faces that share edges.  Each one is reported with its
size and its extent, and the ones that sit over the face are rendered on
their own so that they can be judged by eye before anything is deleted.

Usage:
  blender -b -P scripts/probe_yxz_shells_of.py -- \
    --glb <glb> [--out <png>] [--region x0,x1,y0,y1,z0,z1] [--min-faces 40]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def components(bm):
    """The connected components of a bmesh, as lists of faces."""
    unseen = set(bm.faces)
    groups = []
    while unseen:
        seed = unseen.pop()
        group = [seed]
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour in unseen:
                        unseen.discard(neighbour)
                        group.append(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    return groups


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    min_faces = int(value_after("--min-faces", 40))
    region = value_after("--region")
    if region:
        low, high = [float(part) for part in region.split(",")][:3], [
            float(part) for part in region.split(",")
        ][3:]
    else:
        low, high = (-1e9, -1e9, -1e9), (1e9, 1e9, 1e9)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)

    groups = components(bm)
    print("YXZ_SHELLS total=%d" % len(groups))

    report = []
    for group in groups:
        if len(group) < min_faces:
            continue
        cloud = np.array([list(face.calc_center_median()) for face in group])
        low_corner = cloud.min(axis=0)
        high_corner = cloud.max(axis=0)
        inside = all(
            low[i] <= high_corner[i] and high[i] >= low_corner[i] for i in range(3)
        )
        if not inside:
            continue
        report.append({
            "faces": len(group),
            "low": [round(float(value), 4) for value in low_corner],
            "high": [round(float(value), 4) for value in high_corner],
        })
    report.sort(key=lambda item: item["faces"])
    for index, item in enumerate(report):
        print("YXZ_SHELL %d %s" % (index, json.dumps(item)))
    print("YXZ_SHELL_MATCHES %d" % len(report))

    if out and report:
        wanted = set()
        for group in groups:
            if len(group) < min_faces:
                continue
            cloud = np.array([list(face.calc_center_median()) for face in group])
            low_corner = cloud.min(axis=0)
            high_corner = cloud.max(axis=0)
            if not all(low[i] <= high_corner[i] and high[i] >= low_corner[i]
                       for i in range(3)):
                continue
            wanted.update(face.index for face in group)

        copy = body.data.copy()
        piece = bmesh.new()
        piece.from_mesh(copy)
        piece.faces.ensure_lookup_table()
        bmesh.ops.delete(
            piece,
            geom=[face for face in piece.faces if face.index not in wanted],
            context="FACES",
        )
        piece.to_mesh(copy)
        piece.free()
        obj = bpy.data.objects.new("shells", copy)
        bpy.context.scene.collection.objects.link(obj)
        for target, colour in ((obj, (0.95, 0.12, 0.42, 1.0)),
                               (body, (0.74, 0.77, 0.80, 1.0))):
            target.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            shader = material.node_tree.nodes["Principled BSDF"]
            shader.inputs["Base Color"].default_value = colour
            shader.inputs["Roughness"].default_value = 0.7
            target.data.materials.append(material)

        cam_data = bpy.data.cameras.new("shells")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = 0.62
        cam = bpy.data.objects.new("shells", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        cam.location = Vector((0.19, -0.11, 0.13))
        cam.rotation_euler = (1.5708, 0, 1.5708)
        scene = bpy.context.scene
        scene.camera = cam

        key = bpy.data.lights.new("key", type="SUN")
        key.energy = 3.0
        key_obj = bpy.data.objects.new("key", key)
        scene.collection.objects.link(key_obj)
        key_obj.rotation_euler = (1.0472, 0, 0.8727)

        scene.render.resolution_x = 900
        scene.render.resolution_y = 900
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("YXZ_SHELLS_RENDERED " + str(out))

    bm.free()


if __name__ == "__main__":
    main()
