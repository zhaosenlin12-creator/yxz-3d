"""
 * One piece of the model, on its own.
 *
 * The false colour render says which shell is where, but a shell can be
 * a whole side of the helmet with a torn flap hanging off it, and then
 * "where" is not the question that matters -- "how much of this shell
 * is the flap" is.  So the shell is taken out of the model and the
 * model is taken out of the picture, and what is left is the piece
 * itself, in its own texture, from the angle asked for.
 *
 * Usage:
 *   blender -b -P scripts/render_yxz_isolate.py -- --glb <glb> \
 *     --shells 1,6287 --out <png> [--center x,y,z] [--scale s] [--yaw d]
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


def shells(bm):
    bm.faces.ensure_lookup_table()
    groups = []
    unvisited = set(bm.faces)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        groups.append(group)
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    wanted = {int(piece) for piece in value_after("--shells", "").split(",") if piece.strip()}
    centre = Vector([float(p) for p in value_after("--center", "0.19,0,0.27").split(",")])
    scale = float(value_after("--scale", "0.55"))
    size = int(value_after("--size", "1000"))
    yaw = math.radians(float(value_after("--yaw", "0")))
    pitch = math.radians(float(value_after("--pitch", "0")))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)
    doomed = [face for number, group in enumerate(groups) if number not in wanted
              for face in group]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    scene = bpy.context.scene
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
    scene.render.resolution_percentage = 100

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.10, 0.13, 1.0)
    scene.world = world
    for name, energy, rotation in (
        ("key", 3.4, (0.85, 0.25, 0.45)),
        ("fill", 1.1, (1.25, -0.2, -0.6)),
    ):
        light = bpy.data.lights.new(name, type="SUN")
        light.energy = energy
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.rotation_euler = rotation

    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_ISOLATED %s" % out)


if __name__ == "__main__":
    main()
