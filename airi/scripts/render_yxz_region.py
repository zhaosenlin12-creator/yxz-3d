"""Show one piece of the YXZ character on its own, in place.

A question about the model is usually "is that patch of the atlas the
thing I can see", and answering it needs three things at once: the piece
highlighted, the rest of the character still there to judge it against,
and a camera that looks at the character the way the stage does.

So the piece is coloured, the body is left grey, and the light rig is the
one `render_yxz_head.py` uses, which is the rig the shading was tuned
against.

Usage:
  blender -b -P scripts/render_yxz_region.py -- \
    --glb <glb> --out <png> --uv <u>,<v> [--radius 0.02] \
    [--center 0.20,-0.10,0.15] [--yaw 90] [--scale 0.42]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    uv_value = value_after("--uv", "0,0")
    u, v = [float(part) for part in uv_value.split(",")]
    radius = float(value_after("--radius", 0.02))
    rect = value_after("--rect")
    if rect:
        u0, v0, u1, v1 = [float(part) for part in rect.split(",")]
    else:
        u0, v0, u1, v1 = u - radius, v - radius, u + radius, v + radius
    centre = Vector([float(part) for part in value_after("--center", "0.20,-0.10,0.15").split(",")])
    yaw = math.radians(float(value_after("--yaw", 90)))
    scale = float(value_after("--scale", 0.42))
    size = int(value_after("--size", 900))

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
        if u0 <= cu <= u1 and v0 <= cv <= v1:
            picked.append(face)
    print("YXZ_REGION faces=%d" % len(picked))
    if not picked:
        bm.free()
        return
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
    bm.free()

    for target, colour in ((obj, (0.96, 0.10, 0.40, 1.0)),
                           (body, (0.80, 0.82, 0.85, 1.0))):
        target.data.materials.clear()
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = colour
        shader.inputs["Roughness"].default_value = 0.75
        target.data.materials.append(material)

    cam_data = bpy.data.cameras.new("region")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("region", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    base = Vector((0.0, -1.0, 0.0))
    turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
    cam.location = centre + turned * 2.0
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.2
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.2, 0.4)
    fill = bpy.data.lights.new("fill", type="AREA")
    fill.energy = 60.0
    fill.size = 2.0
    fill_obj = bpy.data.objects.new("fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = Vector((-1.2, -1.6, centre.z + 0.4))
    fill_obj.rotation_euler = (1.1, 0.0, -0.6)

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_REGION_RENDERED " + str(out))


if __name__ == "__main__":
    main()
