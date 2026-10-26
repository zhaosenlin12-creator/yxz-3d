"""Give the shell a thickness, and see what the character looks like.

The scan is a single layer of surface.  Where two pieces of it meet, or
where it was torn, there is a gap, and through the gap you see the
inside of the character's own head -- which no light reaches, so the gap
reads as a black tear.  It is the reason the model looks damaged rather
than painted, and it is everywhere: round the visor, at the shoulders,
at the knees.

Solidify is the answer in one line: it grows a second surface inside the
first and joins them at the edge, so the model becomes a solid object
with a real edge to catch the light.  The inside is given a material of
its own -- a plain, bright, unlit-ish grey -- because the inside of a
toy is not a dark hole, it is a surface in shadow.

Usage:
  blender -b -P scripts/probe_yxz_solidify.py -- --glb <glb> --out <png>
    [--thickness 0.004] [--center x,y,z] [--scale s] [--size n]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main():
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    thickness = float(value_after("--thickness", "0.004"))
    size = int(value_after("--size", "900"))
    scale = float(value_after("--scale", "0.85"))
    centre = Vector([float(p) for p in
                     value_after("--center", "0,0,0.05").split(",")])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    body = max((obj for obj in scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    # A plain, bright material for the inside of the shell.
    inner = bpy.data.materials.new("inner")
    inner.use_nodes = True
    shader = inner.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = (0.62, 0.66, 0.72, 1.0)
    shader.inputs["Roughness"].default_value = 0.85
    body.data.materials.append(inner)

    modifier = body.modifiers.new("solidify", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = 1.0
    modifier.use_even_offset = False
    modifier.use_rim = True
    modifier.material_offset = 1
    modifier.material_offset_rim = 1

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.93, 0.95, 0.97, 1.0)
    scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = size
    scene.render.resolution_y = size

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key.color = (1.0, 0.95, 0.89)
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.15, 0.5)
    fill = bpy.data.lights.new("fill", type="SUN")
    fill.energy = 1.0
    fill.color = (0.72, 0.82, 1.0)
    fill_obj = bpy.data.objects.new("fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.rotation_euler = (1.3, -0.2, -0.7)

    angle = math.radians(float(value_after("--yaw", "0")))
    turned = Vector((math.cos(angle), math.sin(angle), 0.0))
    cam.location = centre + turned.normalized() * 3.0
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()

    bpy.context.view_layer.update()
    print("YXZ_SOLIDIFY " + str(len(body.data.polygons)))
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_SOLID_RENDER " + str(out))


main()
