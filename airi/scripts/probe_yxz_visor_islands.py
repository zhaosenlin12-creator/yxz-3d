"""Which piece of the head is the thing wrong with the visor.

Three defects show on the visor and none of them can be fixed without
knowing which piece of the scan they belong to: a bright bar across the
top of it, a grey plate lying over the upper left of it, and a fringe
of white chips round the rim.  Each is a separate island, and the
islands are numbered, so the head is photographed with every island in
the visor area in a colour of its own and the numbers are printed
beside it.

Usage:
  blender -b -P scripts/probe_yxz_visor_islands.py -- \
    --glb <glb> --out <dir> [--centre 0.038,-0.001,0.094] \
    [--inner 0.20] [--outer 0.295] [--yaw 70]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def islands(bm):
    bm.faces.ensure_lookup_table()
    unvisited = set(bm.faces)
    groups = []
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


PALETTE = [
    (0.95, 0.15, 0.10),
    (0.10, 0.45, 0.95),
    (0.15, 0.80, 0.25),
    (0.98, 0.60, 0.05),
    (0.75, 0.20, 0.90),
    (0.05, 0.80, 0.80),
    (0.98, 0.82, 0.10),
    (0.60, 0.35, 0.10),
    (0.98, 0.30, 0.62),
    (0.45, 0.48, 0.55),
    (0.20, 0.70, 0.45),
]


def look_at(cam, target):
    direction = (Vector(target) - cam.location).normalized()
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main() -> None:
    glb = Path(value_after("--glb"))
    out = Path(value_after("--out"))
    out.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    inner = float(value_after("--inner", "0.20"))
    outer = float(value_after("--outer", "0.295"))
    yaw = float(value_after("--yaw", "70"))
    size = int(value_after("--size", "1000"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene
    body = max((obj for obj in scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    groups = islands(bm)

    def visor_faces(group):
        out = []
        for face in group:
            middle = face.calc_center_median()
            radius = (middle - centre).length
            if inner <= radius <= outer:
                out.append(face)
        return out

    pieces = []
    for number, group in enumerate(groups):
        faces = visor_faces(group)
        if len(faces) < 8:
            continue
        points = [face.calc_center_median() for face in faces]
        average = Vector((sum(p.x for p in points) / len(points),
                          sum(p.y for p in points) / len(points),
                          sum(p.z for p in points) / len(points)))
        # The mean UV of a piece is what it is painted with.
        u = 0.0
        v = 0.0
        count = 0
        for face in faces:
            for loop in face.loops:
                u += loop[uv_layer].uv.x
                v += loop[uv_layer].uv.y
                count += 1
        pieces.append({
            "island": number,
            "faces": len(faces),
            "total": len(group),
            "at": [round(c, 4) for c in average],
            "rMin": round(min((p - centre).length for p in points), 4),
            "rMax": round(max((p - centre).length for p in points), 4),
            "xMin": round(min(p.x for p in points), 4),
            "xMax": round(max(p.x for p in points), 4),
            "zMin": round(min(p.z for p in points), 4),
            "zMax": round(max(p.z for p in points), 4),
            "uv": [round(u / count, 4), round(v / count, 4)],
        })
    pieces.sort(key=lambda piece: -piece["faces"])

    plain = bpy.data.materials.new("plain")
    plain.use_nodes = True
    plain.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.82, 0.83, 0.85, 1)
    plain.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    body.data.materials.clear()
    body.data.materials.append(plain)
    for face in bm.faces:
        face.material_index = 0

    legend = []
    for order, piece in enumerate(pieces[:11]):
        material = bpy.data.materials.new("piece%d" % piece["island"])
        material.use_nodes = True
        colour = PALETTE[order % len(PALETTE)]
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
            *colour, 1)
        material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.55
        body.data.materials.append(material)
        piece["slot"] = order + 1
        piece["rgb"] = colour
        for face in groups[piece["island"]]:
            face.material_index = order + 1
        legend.append(piece)

    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    # A light rig and a camera on the visor.
    for name, location, energy, size_ in (
        ("key", (0.9, -1.3, 1.1), 260, 1.6),
        ("fill", (-1.2, -0.9, 0.2), 60, 2.0),
        ("rim", (0.2, 1.4, 1.0), 120, 1.4),
    ):
        lamp = bpy.data.lights.new(name, "AREA")
        lamp.energy = energy
        lamp.size = size_
        obj = bpy.data.objects.new(name, lamp)
        obj.location = location
        scene.collection.objects.link(obj)
        look_at(obj, centre)

    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.55, 0.57, 0.60, 1)
    scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 85
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    distance = float(value_after("--distance", "1.45"))
    for name, degrees in (("front", 0.0), ("brow", yaw)):
        angle = degrees * 3.141592653589793 / 180.0
        cam.location = centre + Vector((
            distance * __import__("math").cos(angle),
            distance * __import__("math").sin(angle),
            distance * 0.22,
        ))
        look_at(cam, centre)
        scene.render.resolution_x = size
        scene.render.resolution_y = size
        scene.render.filepath = str(out / ("visor-" + name + ".png"))
        bpy.ops.render.render(write_still=True)
        print("YXZ_VISOR_VIEW " + str(out / ("visor-" + name + ".png")))

    (out / "islands.json").write_text(
        json.dumps({"glb": str(glb), "legend": legend}, indent=1),
        encoding="utf-8")
    print("YXZ_VISOR_ISLANDS " + json.dumps(legend[:11]))


if __name__ == "__main__":
    main()
