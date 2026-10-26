"""The model, from every side, the way the page draws it.

The previews that came before this one drew every face, front and back,
which is not what the page does: the page culls the back faces, so a
surface turned the wrong way round is simply not there.  Looking at a
preview that does not cull tells you about the preview and not about the
character, and it is how a solid helmet came to be read as a translucent
one.

So this culls, like the page, and it uses the model's own textures on a
light background, which is the background the character actually stands
on.

Usage:
  blender -b -P scripts/render_yxz_views.py -- --glb <glb> --out <prefix>
    [--yaw 0,45,90,135,180,225,270,315] [--size 700] [--scale 0.9]
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
    size = int(value_after("--size", "700"))
    scale = float(value_after("--scale", "0.9"))
    centre = Vector([float(p) for p in
                     value_after("--center", "0,0,0.05").split(",")])
    flat = "--flat" in sys.argv

    yaws = [float(v) for v in
            value_after("--yaw", "0,45,90,135,180,225,270,315").split(",")]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for mat in obj.data.materials:
            if mat is None:
                continue
            mat.use_backface_culling = True

    if flat:
        # The model with the paint taken off it.  A mark that is still
        # there with the paint gone is a hole in the shell; a mark that
        # goes with the paint was only ever a mark.
        plain = bpy.data.materials.new("plain")
        plain.use_nodes = True
        shade = plain.node_tree.nodes["Principled BSDF"]
        shade.inputs["Base Color"].default_value = (0.82, 0.85, 0.88, 1.0)
        shade.inputs["Roughness"].default_value = 0.45
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            obj.data.materials.append(plain)

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

    for yaw in yaws:
        angle = math.radians(yaw)
        turned = Vector((math.cos(angle), math.sin(angle), 0.0))
        cam.location = centre + turned.normalized() * 3.0
        look = (centre - cam.location).normalized()
        cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out.parent / ("%s-%03d.png" % (out.name, int(yaw))))
        bpy.ops.render.render(write_still=True)
        print("YXZ_VIEW " + scene.render.filepath)


main()

