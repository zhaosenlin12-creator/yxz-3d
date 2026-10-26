"""Find the geometry that a patch of the texture atlas belongs to.

 * The stage is the only place the shipping look can be judged, so when
 * something on the character looks wrong the question is which piece
 * of geometry it is.  Picking it in the browser gives its texture
 * coordinate, and the texture coordinate is the join: the same UV in
 * Blender is the same surface, and from there the piece can be looked
 * at on its own and dealt with.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_uvregion.py -- \
 *     --glb <glb> --uv <u>,<v> [--radius 0.02] [--out <png>]
"""

from __future__ import annotations

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


def main() -> None:
    glb = value_after("--glb")
    u, v = [float(part) for part in value_after("--uv").split(",")]
    radius = float(value_after("--radius", 0.02))
    out = value_after("--out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active

    picked = []
    for face in bm.faces:
        cu = sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops)
        cv = sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops)
        if abs(cu - u) <= radius and abs(cv - v) <= radius:
            picked.append(face)

    if not picked:
        print("YXZ_UVREGION none")
        bm.free()
        return

    cloud = np.array([list(face.calc_center_median()) for face in picked])
    uvs = np.array([
        [
            sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops),
            sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops),
        ]
        for face in picked
    ])
    print("YXZ_UVREGION faces=%d low=%s high=%s middle=%s"
          % (len(picked),
             [round(float(value), 4) for value in cloud.min(axis=0)],
             [round(float(value), 4) for value in cloud.max(axis=0)],
             [round(float(value), 4) for value in cloud.mean(axis=0)]))
    print("YXZ_UVREGION_UV low=%s high=%s"
          % ([round(float(value), 5) for value in uvs.min(axis=0)],
             [round(float(value), 5) for value in uvs.max(axis=0)]))

    if out:
        keep = set(face.index for face in picked)
        copy = body.data.copy()
        piece = bmesh.new()
        piece.from_mesh(copy)
        piece.faces.ensure_lookup_table()
        bmesh.ops.delete(
            piece,
            geom=[face for face in piece.faces if face.index not in keep],
            context="FACES",
        )
        piece.to_mesh(copy)
        piece.free()
        obj = bpy.data.objects.new("region", copy)
        bpy.context.scene.collection.objects.link(obj)
        for target, colour in ((obj, (0.95, 0.1, 0.55, 1.0)),
                               (body, (0.55, 0.58, 0.62, 1.0))):
            target.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            shader = material.node_tree.nodes["Principled BSDF"]
            shader.inputs["Base Color"].default_value = colour
            shader.inputs["Roughness"].default_value = 0.7
            target.data.materials.append(material)
        print("YXZ_UVREGION_OBJ " + str(out))

        # Look at the piece on its own, with the rest of the character
        # behind it in grey, so it can be seen for what it is.
        middle = Vector([float(value) for value in cloud.mean(axis=0)])
        span = max(
            float((cloud.max(axis=0) - cloud.min(axis=0)).max()) * 2.5, 0.15
        )
        cam_data = bpy.data.cameras.new("region")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = span
        cam = bpy.data.objects.new("region", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        look = (middle - Vector((1.0, -1.0, 0.35))).normalized()
        cam.location = middle + look * 2.0
        cam.rotation_euler = (-look).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.camera = cam

        key = bpy.data.lights.new("key", type="SUN")
        key.energy = 3.0
        key_obj = bpy.data.objects.new("key", key)
        bpy.context.scene.collection.objects.link(key_obj)
        # A sun shines along its own -Z, so aiming it down the view
        # direction lights whatever the camera is looking at.
        key_obj.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()

        scene = bpy.context.scene
        scene.render.resolution_x = 800
        scene.render.resolution_y = 800
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("YXZ_UVREGION_RENDERED " + str(out))
    bm.free()


if __name__ == "__main__":
    main()
