"""One part of the character, large enough to judge.

The whole-figure captures are good at answering "does it read as solid"
and useless at answering "what is that line across the jaw".  A defect
worth fixing is a few millimetres across, so it has to be looked at from
close enough that its own shape is the subject, with the same textures
the page draws with -- anything else and the answer is about the render
rather than about the model.

Usage:
  blender -b -P scripts/render_yxz_zoom.py -- --glb <glb> --out <png>
    [--center x,y,z] [--scale 0.12] [--size 1200] [--yaw 90] [--pitch 0]
    [--flat]   draw the shell in one grey instead of in its own textures
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


def background(scene, colour):
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    node = world.node_tree.nodes["Background"]
    node.inputs[0].default_value = (colour[0], colour[1], colour[2], 1.0)
    node.inputs[1].default_value = 1.0
    scene.world = world


def main():
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(p) for p in
                     value_after("--center", "0.20,0,0.10").split(",")])
    scale = float(value_after("--scale", "0.12"))
    size = int(value_after("--size", "1200"))
    yaw = math.radians(float(value_after("--yaw", "90")))
    pitch = math.radians(float(value_after("--pitch", "0")))
    flat = "--flat" in sys.argv
    double = "--double" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    if flat:
        # With one flat grey there is nothing for a texture seam or a baked
        # speckle to hide behind, so what is left on the surface is shape.
        # Every mesh is flattened, not just the body: the face controls are
        # separate objects with their own dark materials, and leaving those
        # alone puts the eyes and the mouth into a picture that is supposed
        # to be about the shell.
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = (0.82, 0.84, 0.88, 1.0)
        shader.inputs["Roughness"].default_value = 0.8
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            obj.data.materials.append(material)

    scene = bpy.context.scene

    # The page culls the back faces, so a preview that does not is
    # showing the character with the inside of its own shell lit up.
    if not double:
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH":
                continue
            for mat in obj.data.materials:
                if mat is not None:
                    mat.use_backface_culling = True
    cam_data = bpy.data.cameras.new("zoom")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("zoom", cam_data)
    scene.collection.objects.link(cam)
    turned = Vector((math.cos(yaw), -math.sin(yaw) * math.cos(pitch), math.sin(pitch)))
    cam.location = centre + turned.normalized() * 3.0
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    background(scene, (0.09, 0.10, 0.13))

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.4
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.85, 0.25, 0.45)

    fill = bpy.data.lights.new("fill", type="SUN")
    fill.energy = 1.1
    fill_obj = bpy.data.objects.new("fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.rotation_euler = (1.25, -0.2, -0.6)

    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_ZOOM %s" % out)


main()

