"""Show what the bubble rule would take off.

The rule that finds the clear bubble over the helmet -- the geometry that
stands clear of the sphere the helmet is built on -- also catches the
raised hand, which is clear of the head too, and taking the hand off the
character is a worse thing than a glassy dome.  So the faces the rule
selects are painted and everything else is taken away, and the picture
answers the question the numbers cannot.

Usage:
  blender -b -P scripts/probe_yxz_bubble_mask.py -- \
    --glb <glb> --out <dir> [--centre 0.038,-0.001,0.094] \
    [--bubble-radius 0.300] [--far-radius 0.42] [--keep-box ...]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = Path(value_after("--glb"))
    out = Path(value_after("--out"))
    out.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    bubble_radius = float(value_after("--bubble-radius", "0.300"))
    far_radius = float(value_after("--far-radius", "0.42"))
    floor = float(value_after("--floor", "-0.16"))
    keep = value_after("--keep-box", "0.15,-0.22,0.22,0.28,0.14,0.42")
    keep_box = [float(v) for v in keep.split(",")]

    def in_keep_box(point):
        return all(keep_box[axis] <= point[axis] <= keep_box[axis + 3]
                   for axis in range(3))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene
    body = max((obj for obj in scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    keep_faces = []
    bubble_faces = []
    for face in bm.faces:
        middle = face.calc_center_median()
        distance = (middle - centre).length
        bubble = (distance > bubble_radius and distance <= far_radius
                  and middle.z >= centre.z + floor
                  and not in_keep_box(middle))
        if not bubble:
            keep_faces.append(face)
        else:
            bubble_faces.append(face)

    # Two colours in one picture: the faces the rule takes in red, the
    # rest of the character in white.  Where they overlap is where the
    # rule is wrong.
    for face in bubble_faces:
        face.material_index = 1
    for face in keep_faces:
        face.material_index = 0
    material = bpy.data.materials.new("keep")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        shader.inputs["Base Color"].default_value = (0.92, 0.92, 0.92, 1.0)
        shader.inputs["Roughness"].default_value = 0.6
    red = bpy.data.materials.new("bubble")
    red.use_nodes = True
    shader = red.node_tree.nodes.get("Principled BSDF")
    if shader:
        shader.inputs["Base Color"].default_value = (0.85, 0.12, 0.12, 1.0)
        shader.inputs["Roughness"].default_value = 0.6
    body.data.materials.clear()
    body.data.materials.append(material)
    body.data.materials.append(red)
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    # A camera on the head, and the lights the other renders use.
    camera_data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (centre.x + 1.2, centre.y - 0.55, centre.z + 0.25)
    camera.rotation_euler = (math.radians(80.0), 0.0, math.radians(65.0))
    scene.camera = camera
    light = bpy.data.objects.new("light", bpy.data.lights.new("light", "SUN"))
    light.rotation_euler = (math.radians(50.0), 0.0, math.radians(120.0))
    scene.collection.objects.link(light)
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs[0].default_value = (0.15, 0.17, 0.2, 1.0)
        background.inputs[1].default_value = 1.0
    scene.world = world

    for name, location in (
        ("mask-front", (centre.x + 1.2, centre.y - 0.55, centre.z + 0.25)),
        ("mask-top", (centre.x + 0.1, centre.y - 0.1, centre.z + 1.2)),
        ("mask-side", (centre.x, centre.y - 1.4, centre.z + 0.15)),
    ):
        camera.location = location
        if name == "mask-top":
            camera.rotation_euler = (0.0, 0.0, 0.0)
        elif name == "mask-side":
            camera.rotation_euler = (math.radians(90.0), 0.0, math.radians(-90.0))
        else:
            camera.rotation_euler = (math.radians(80.0), 0.0, math.radians(65.0))
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_BUBBLE_MASK " + str(out / f"{name}.png"))


if __name__ == "__main__":
    main()
