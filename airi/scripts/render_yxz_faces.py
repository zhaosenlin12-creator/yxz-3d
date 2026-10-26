"""Render the head with its front and back faces in different colours.

A scanned shell is single sided, so from any angle the far wall of the
model is turned away from the camera.  Painted white, the far wall is
simply dark, and a dark patch on a head reads as a hole whether it is a
hole or the inside of the bowl.  Colouring the two sides differently
settles the question: red is a surface that is facing away, and black is
no surface at all.

Usage:
  blender -b -P scripts/render_yxz_faces.py -- \
    --glb <glb> --out <png> [--center 0.038,-0.001,0.094] [--yaw 0]
    [--pitch 0] [--scale 0.72] [--size 700]
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    centre = Vector([float(part) for part in
                     value_after("--center", "0.038,-0.001,0.094").split(",")])
    scale = float(value_after("--scale", "0.72"))
    size = int(value_after("--size", "700"))
    yaw = math.radians(float(value_after("--yaw", "0.0")))
    pitch = math.radians(float(value_after("--pitch", "0.0")))
    distance = float(value_after("--distance", "2.0"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene
    for stray in [o for o in scene.objects if o.type == "MESH" and not o.data.materials]:
        mesh = stray.data
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(mesh)

    material = bpy.data.materials.new("sides")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    mix = nodes.new("ShaderNodeMixRGB")
    backfacing = nodes.new("ShaderNodeNewGeometry")
    mix.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    mix.inputs[2].default_value = (0.85, 0.12, 0.16, 1.0)
    links.new(backfacing.outputs["Backfacing"], mix.inputs[0])
    links.new(mix.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)

    cam_data = bpy.data.cameras.new("head")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("head", cam_data)
    scene.collection.objects.link(cam)
    base = Vector((0.0, -1.0, 0.0))
    turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
    cam.location = centre + turned * (distance * math.cos(pitch))
    cam.location.z += distance * math.sin(pitch)
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    world = bpy.data.worlds.new("probe")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.08, 1.0)

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out
    scene.render.engine = "BLENDER_EEVEE"
    bpy.ops.render.render(write_still=True)
    print("YXZ_FACES_RENDERED " + str(out))


if __name__ == "__main__":
    main()
