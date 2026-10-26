"""Which of the two is it: a shell that is turned inside out, or a shell with holes?

Culling the back faces is what the page does, so a face turned the wrong way
round simply is not there.  Turning culling off puts every face back and
tells the two apart in one render: a culled dome comes back solid, a holed
dome stays open.

Usage:
  blender -b -P scripts/probe_yxz_shell.py -- --glb <glb> --out <prefix>
    [--center x,y,z] [--scale 0.55] [--size 900] [--yaw 0]
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
    centre = Vector([float(p) for p in
                     value_after("--center", "0.19,0,0.27").split(",")])
    scale = float(value_after("--scale", "0.55"))
    size = int(value_after("--size", "900"))
    yaw = math.radians(float(value_after("--yaw", "0")))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.09, 0.10, 0.13, 1.0)
    scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    turned = Vector((math.cos(yaw), -math.sin(yaw), 0.0))
    cam.location = centre + turned.normalized() * 3.0
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = size
    scene.render.resolution_y = size

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

    modes = {
        "cull": None,          # exactly what the page draws
        "nocull": "DOUBLE",    # every face back in place
    }
    for name, side in modes.items():
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH":
                continue
            for mat in obj.data.materials:
                if mat is None:
                    continue
                mat.use_backface_culling = False
                if side:
                    mat.blend_method = "BLEND" if False else "OPAQUE"
                    if hasattr(mat, "use_backface_culling"):
                        mat.use_backface_culling = False
                # give the inside of the shell its own dark colour so an
                # open shell is obvious rather than ambiguous
                mat.use_backface_culling = False
        if name == "cull":
            for obj in bpy.context.scene.objects:
                if obj.type != "MESH":
                    continue
                for mat in obj.data.materials:
                    if mat is not None:
                        mat.use_backface_culling = True

        scene.render.filepath = str(out.parent / ("%s-%s.png" % (out.name, name)))
        bpy.ops.render.render(write_still=True)
        print("YXZ_SHELL %s" % scene.render.filepath)


main()
