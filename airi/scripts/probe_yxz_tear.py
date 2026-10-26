"""Show where the mesh is torn.

The scan came apart along a boundary: one long open rim runs around the
top of the helmet, and the sheets that were meant to close it are still
there, standing up like torn flaps.  A picture of that rim settles
which piece is which, so the rim is drawn on the model and the model is
rendered from the front.

Usage:
  blender -b -P scripts/probe_yxz_tear.py -- \
    --glb <glb> --out <png> [--yaw 0] [--pitch 0] [--size 900]
"""

from __future__ import annotations

import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def setup_world():
    world = bpy.data.worlds.new("probe")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (0.06, 0.07, 0.09, 1.0)
    background.inputs[1].default_value = 1.0

    data = bpy.cameras.new("camera")
    camera = bpy.data.objects.new("camera", data)
    bpy.context.scene.collection.objects.link(camera)
    data.lens = 85.0
    data.clip_start = 0.01
    data.clip_end = 100.0
    scene = bpy.context.scene
    scene.camera = camera

    for name, location, energy in (
            ("key", (-1.6, -2.0, 2.4), 420.0),
            ("fill", (2.4, -1.6, 0.6), 160.0),
            ("rim", (0.4, 2.6, 1.8), 200.0)):
        light = bpy.data.lights.new(name, type="AREA")
        light.energy = energy
        light.size = 2.5
        holder = bpy.data.objects.new(name, light)
        scene.collection.objects.link(holder)
        holder.location = Vector(location)
        holder.rotation_euler = (Vector((0.0, 0.0, 0.28)) - holder.location).to_track_quat("-Z", "Y").to_euler()

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    bpy.context.view_layer.update()


def flat_material(name, colour):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = colour
    shader.inputs["Roughness"].default_value = 0.6
    return material


def main():
    source = value_after("--glb")
    out = value_after("--out", "docs/yxz-diag/tear.png")
    yaw = math.radians(float(value_after("--yaw", 0.0)))
    pitch = math.radians(float(value_after("--pitch", 0.0)))
    size = int(value_after("--size", 900))
    center = Vector([float(part) for part in value_after("--center", "0,0,0.28").split(",")])
    scale = float(value_after("--scale", 0.55))
    distance = float(value_after("--distance", 2.0))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    for stray in [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.data.materials]:
        mesh = stray.data
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    body = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    boundary = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    print("YXZ_TEAR boundary_edges=%d" % len(boundary))
    if boundary:
        points = np.array([[v.co.x, v.co.y, v.co.z] for edge in boundary for v in edge.verts])
        print("YXZ_TEAR bbox " + json.dumps({
            "low": [round(float(c), 4) for c in points.min(axis=0)],
            "high": [round(float(c), 4) for c in points.max(axis=0)],
        }))

    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.62, 0.64, 0.68, 1.0)))
    body.data.materials.append(flat_material("tear", (0.95, 0.08, 0.35, 1.0)))
    marked = set()
    for edge in boundary:
        for face in edge.link_faces:
            marked.add(face.index)
    for polygon in body.data.polygons:
        polygon.material_index = 1 if polygon.index in marked else 0
    body.data.update()

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    camera = scene.camera
    camera.location = center + Vector((
        math.sin(yaw) * math.cos(pitch),
        -math.cos(yaw) * math.cos(pitch),
        math.sin(pitch),
    )) * distance
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_TEAR_RENDER " + out)


if __name__ == "__main__":
    main()
