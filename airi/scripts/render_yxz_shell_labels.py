"""The head with each of the pieces that sit on it picked out in a
colour of its own.

The crown of the helmet is made of several large pieces, and the wreck
of the scan's old halo is lying on top of them.  Which is which cannot
be told from a list of sizes -- a torn flap and a panel of the helmet
are the same size and the same shape of thing -- so the pieces are
coloured and photographed, and the colours are printed alongside so
the picture can be read.

Usage:
  blender -b -P scripts/render_yxz_shell_labels.py -- \
    --glb <glb> --shells 1,2,3 --out <png> \
    [--center x,y,z] [--scale s] [--yaw d] [--pitch d] [--size 900]
"""

from __future__ import annotations

import json
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


# A palette that stays apart on a white model: saturated, and each one
# far from the next in hue.
PALETTE = [
    (0.90, 0.10, 0.10),
    (0.10, 0.35, 0.95),
    (0.10, 0.80, 0.20),
    (0.95, 0.55, 0.05),
    (0.70, 0.15, 0.85),
    (0.05, 0.80, 0.80),
    (0.95, 0.80, 0.10),
    (0.55, 0.35, 0.10),
    (0.95, 0.25, 0.60),
    (0.40, 0.45, 0.55),
]


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    wanted = [int(piece) for piece in value_after("--shells", "").split(",") if piece.strip()]
    centre = Vector([float(p) for p in value_after("--center", "0.09,0,0.31").split(",")])
    scale = float(value_after("--scale", "0.5"))
    size = int(value_after("--size", "900"))
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

    # Everything that is not on the list is turned into a plain grey
    # shell, so the pieces that are on it stand out and the rest of the
    # helmet still gives them a shape to sit on.
    flat = bpy.data.materials.new("plain")
    flat.use_nodes = True
    flat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.72, 0.73, 0.76, 1)
    flat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    body.data.materials.clear()
    body.data.materials.append(flat)

    legend = []
    for number, piece in enumerate(wanted):
        colour = PALETTE[number % len(PALETTE)]
        material = bpy.data.materials.new("piece%d" % piece)
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*colour, 1)
        material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
        body.data.materials.append(material)
        legend.append({"index": piece, "slot": number + 1, "rgb": colour})
        for face in groups[piece]:
            face.material_index = number + 1
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
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.92, 0.94, 0.96, 1.0)
    scene.world = world
    for name, energy, rotation in (
        ("key", 2.6, (0.85, 0.25, 0.45)),
        ("fill", 1.0, (1.25, -0.2, -0.6)),
    ):
        light = bpy.data.lights.new(name, type="SUN")
        light.energy = energy
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.rotation_euler = rotation

    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_LABELS %s %s" % (out, json.dumps(legend)))


if __name__ == "__main__":
    main()
