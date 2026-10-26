"""What is actually sitting on the crown of the helmet.

The character reads as shattered because there are pieces of shell lying
on the shell, a fraction of a millimetre off it, and the depth test
cannot tell the two apart.  So the pieces have to be named before they
can be taken away, and a list of sizes will not name them: a torn flap
and a panel of the helmet are the same size and the same shape of thing.

So the head is photographed with every piece in a colour of its own, and
the numbers are printed next to the picture.  The rebuilt crown is found
by the one thing that is the same about all of its faces -- they were
all given the same point in the texture atlas -- and everything else on
the head is coloured by the piece it belongs to.

Usage:
  blender -b -P scripts/probe_yxz_crown_shred.py -- \
    --glb <glb> --out <dir> [--centre 0.038,-0.001,0.094] [--radius 0.34]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def islands(bm):
    """Every connected group of faces."""
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
    (0.55, 0.20, 0.30),
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
    radius = float(value_after("--radius", "0.34"))
    size = int(value_after("--size", "1000"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    groups = islands(bm)
    main_group = max(range(len(groups)), key=lambda i: len(groups[i]))

    def head_faces(group):
        return [face for face in group
                if (face.calc_center_median() - centre).length < radius]

    # The rebuilt crown is the one piece of the head whose faces were all
    # given the same point in the atlas, so that is how it is found.
    uv_counter = Counter()
    for group in groups:
        for face in head_faces(group):
            for loop in face.loops:
                uv = loop[uv_layer].uv
                uv_counter[(round(uv.x, 5), round(uv.y, 5))] += 1
    crown_uv, crown_uv_count = uv_counter.most_common(1)[0]

    def is_crown(face):
        for loop in face.loops:
            uv = loop[uv_layer].uv
            if abs(uv.x - crown_uv[0]) < 1e-4 and abs(uv.y - crown_uv[1]) < 1e-4:
                return True
        return False

    # The pieces on the head, biggest first.
    pieces = []
    for number, group in enumerate(groups):
        if number == main_group:
            continue
        faces = head_faces(group)
        if not faces:
            continue
        points = [face.calc_center_median() for face in faces]
        average = Vector((sum(p.x for p in points) / len(points),
                          sum(p.y for p in points) / len(points),
                          sum(p.z for p in points) / len(points)))
        pieces.append({
            "island": number,
            "faces": len(faces),
            "total": len(group),
            "at": [round(v, 4) for v in average],
            "rMin": round(min((p - centre).length for p in points), 4),
            "rMax": round(max((p - centre).length for p in points), 4),
            "zMin": round(min(p.z for p in points), 4),
            "zMax": round(max(p.z for p in points), 4),
            "xMin": round(min(p.x for p in points), 4),
            "xMax": round(max(p.x for p in points), 4),
            "crown": sum(1 for face in faces if is_crown(face)),
        })
    pieces.sort(key=lambda piece: -piece["faces"])

    # The colours.
    plain = bpy.data.materials.new("plain")
    plain.use_nodes = True
    plain.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.80, 0.81, 0.83, 1)
    plain.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    crown_mat = bpy.data.materials.new("crown")
    crown_mat.use_nodes = True
    crown_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.20, 0.80, 0.35, 1)
    crown_mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
    body.data.materials.clear()
    body.data.materials.append(plain)
    body.data.materials.append(crown_mat)

    for face in bm.faces:
        face.material_index = 0
    for face in bm.faces:
        if is_crown(face):
            face.material_index = 1

    legend = []
    for order, piece in enumerate(pieces[:11]):
        material = bpy.data.materials.new("piece%d" % piece["island"])
        material.use_nodes = True
        colour = PALETTE[order % len(PALETTE)]
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*colour, 1)
        material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.55
        body.data.materials.append(material)
        piece["slot"] = order + 2
        piece["rgb"] = colour
        for face in groups[piece["island"]]:
            face.material_index = order + 2
        legend.append(piece)

    # A second reading of the same head: every piece that stands off the
    # dome in one colour, and every piece that is no thicker than a sheet
    # of paper in another.  Those two sets are where the litter is.
    import numpy as np

    def thickness_of(points):
        if len(points) < 3:
            return 0.0
        array = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
        array -= array.mean(axis=0)
        return float(np.linalg.svd(array, compute_uv=False)[2]) * 2.0

    off_dome = bpy.data.materials.new("offdome")
    off_dome.use_nodes = True
    off_dome.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.95, 0.15, 0.10, 1)
    off_dome.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
    paper = bpy.data.materials.new("paper")
    paper.use_nodes = True
    paper.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.95, 0.35, 0.85, 1)
    paper.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
    for material in (off_dome, paper):
        body.data.materials.append(material)
    off_slot = len(body.data.materials) - 2
    paper_slot = len(body.data.materials) - 1

    diagnostic = []
    for group in groups:
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            diagnostic.append(0)
            continue
        radii = [(p - centre).length for p in points]
        if min(radii) > 0.36:
            diagnostic.append(0)
            continue
        stands_off = max(radii) > 0.2905
        is_paper = thickness_of(points) < 0.05
        diagnostic.append(off_slot if (stands_off and not is_paper)
                          else (paper_slot if is_paper else 0))

    bm.to_mesh(body.data)
    body.data.update()
    bm.free()


    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("zoom")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 0.78
    cam = bpy.data.objects.new("zoom", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.95, 0.96, 0.97, 1.0)
    scene.world = world
    for name, energy, rotation in (
        ("key", 3.0, (0.75, 0.30, 0.40)),
        ("fill", 1.2, (1.20, -0.25, -0.55)),
    ):
        light = bpy.data.lights.new(name, type="SUN")
        light.energy = energy
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.rotation_euler = rotation

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100

    views = {
        "front": Vector((1.0, 0.0, 0.10)),
        "three-quarter": Vector((0.72, -0.62, 0.18)),
        "top": Vector((0.34, -0.30, 0.90)),
    }
    cam_data.type = "PERSP"
    cam_data.lens = (1.05 / 0.62) * 18.0
    for name, direction in views.items():
        cam.location = centre + direction.normalized() * 1.05
        look_at(cam, centre)
        cam_data.lens = (1.05 / 0.62) * 18.0
        scene.render.filepath = str(out / f"crown-{name}.png")
        bpy.ops.render.render(write_still=True)

    # The same three photographs again, this time reading the head for
    # the litter instead of for the pieces.
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    groups = islands(bm)
    for number, group in enumerate(groups):
        for face in group:
            face.material_index = diagnostic[number]
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()
    for name, direction in views.items():
        cam.location = centre + direction.normalized() * 1.05
        look_at(cam, centre)
        cam_data.lens = (1.05 / 0.62) * 18.0
        scene.render.filepath = str(out / f"litter-{name}.png")
        bpy.ops.render.render(write_still=True)

    print("YXZ_SHRED " + json.dumps({
        "glb": str(glb),
        "islands": len(groups),
        "mainIsland": main_group,
        "mainFaces": len(groups[main_group]),
        "crownUV": crown_uv,
        "crownUVFaces": crown_uv_count,
        "pieces": legend,
    }))


if __name__ == "__main__":
    main()
