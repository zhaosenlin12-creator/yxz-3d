"""
 * Which pieces of the scan are rubble?
 *
 * The scan is a photograph turned into geometry, and the pieces of it
 * that were hardest to see come back as blades: thin, flat, torn
 * shells that stick out of the silhouette of the character like hair.
 * They are what makes the head read as shattered, and they are not
 * where the light is wrong -- they are pieces of surface that were
 * never part of the character.
 *
 * A blade can be told from a surface without looking at it.  A piece
 * of the character's shell is a surface with thickness: it has a front
 * and a back and a gap between them.  A blade is a surface with none,
 * so every point of it lies close to one plane, and the piece is thin
 * next to how big it is.  The numbers below are that measurement:
 *
 *   extent    how far the piece reaches, corner to corner
 *   thickness how far the piece strays from the plane it lies in
 *   fatness   thickness over extent -- the piece's thinness, made a
 *             ratio so that a small splinter and a large sheet can be
 *             judged by the same rule
 *   solidity  area over the square of the extent -- how much of the
 *             room it takes up the piece actually fills
 *
 * The pieces that are rubble are the thin ones that are also long and
 * thin at the same time.  A helmet is a surface with a little
 * curvature to it and a lot of it, so it is fat and solid; a blade
 * that flew off the crown of the head is thin, long and sparse.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_shards.py -- --glb <glb> \
 *     --out <prefix> [--centre x,y,z] [--scale s]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
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


def measure(group):
    """How long, how narrow, how much of its own room a piece fills."""
    points = np.array(
        [[vert.co.x, vert.co.y, vert.co.z] for face in group for vert in face.verts],
        dtype=np.float64,
    )
    if len(points) < 3:
        return None
    centre = points.mean(axis=0)
    spread = points - centre
    # The axes of the piece itself: the two directions it spreads in
    # and the one it is thin in.
    _, singular, axes = np.linalg.svd(spread, full_matrices=False)
    if singular[0] <= 1e-12:
        return None
    length = float(singular[0] * 2.0)
    width = float(singular[1] * 2.0)
    extent = math.sqrt(length * length + width * width)
    area = float(sum(face.calc_area() for face in group))
    # How narrow the piece is next to how long it is.  A blade of torn
    # surface is a sliver: long in one direction, thin in the other.
    # A piece of a dome is broad in both.
    elongation = width / max(length, 1e-9)
    # How much of the room it takes up the piece actually fills.  A
    # torn sliver is mostly hole; a dome fills its own outline.
    fill = area / max(length * width, 1e-12)
    return {
        "centre": [round(float(v), 4) for v in centre],
        "extent": round(extent, 5),
        "length": round(length, 5),
        "width": round(width, 5),
        "elongation": round(elongation, 4),
        "fill": round(min(fill, 9.99), 4),
        "area": round(area, 6),
    }


def setup_camera(scene, centre, scale, size):
    cam_data = bpy.data.cameras.new("zoom")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("zoom", cam_data)
    scene.collection.objects.link(cam)
    cam.location = centre + Vector((3.0, 0.0, 0.0))
    cam.rotation_euler = (math.radians(90.0), 0.0, math.radians(90.0))
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out", "docs/yxz-diag/shards"))
    out.parent.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(p) for p in value_after("--centre", "0.19,0,0.28").split(",")])
    scale = float(value_after("--scale", "0.55"))
    size = int(value_after("--size", "1000"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)
    body_group = max(groups, key=len)
    body_id = groups.index(body_group)

    rows = []
    for number, group in enumerate(groups):
        numbers = measure(group)
        if numbers is None:
            continue
        numbers["id"] = number
        numbers["faces"] = len(group)
        numbers["isBody"] = group is body_group
        rows.append(numbers)

    with open(str(out.with_name(out.name + ".json")), "w", encoding="utf-8") as handle:
        json.dump({"bodyId": body_id, "shells": rows}, handle)

    # A picture of the verdict, so the numbers can be checked by eye:
 # the pieces the rule calls rubble are painted red, everything else is
    # painted grey.
    scene = bpy.context.scene
    setup_camera(scene, centre, scale, size)
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    node = world.node_tree.nodes["Background"]
    node.inputs[0].default_value = (0.09, 0.10, 0.13, 1.0)
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

    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    def unlit(colour):
        material = bpy.data.materials.new("m")
        material.use_nodes = True
        tree = material.node_tree
        for node in list(tree.nodes):
            if node.type != "OUTPUT_MATERIAL":
                tree.nodes.remove(node)
        output = tree.nodes["Material Output"]
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = (*colour, 1.0)
        tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
        return material

    grey = unlit((0.55, 0.55, 0.55))
    red = unlit((1.0, 0.0, 0.0))
    body.data.materials.clear()
    body.data.materials.append(grey)
    body.data.materials.append(red)

    # The rule, written out.  A piece of the shell is rubble when it is
    # a sliver -- long in one direction, thin in the other, and mostly
    # hole where it lies -- or when it is a speck too small to be any
    # part of the character.  The centre has to be in the head as well,
    # because the wings are thin on purpose.
    head_only = value_after("--head-only", "1") != "0"

    def is_rubble(row):
        if row["isBody"]:
            return False
        centre = row["centre"]
        if head_only and not (centre[2] > 0.14 and abs(centre[1]) < 0.16):
            return False
        blade = (
            row["extent"] > 0.004
            and row["elongation"] < 0.30
            and row["fill"] < 0.60
        )
        speck = row["faces"] <= 14 and row["extent"] < 0.014
        return blade or speck

    verdict = {row["id"]: row for row in rows}
    for number, group in enumerate(groups):
        row = verdict.get(number)
        if row is None:
            continue
        for face in group:
            face.material_index = 1 if is_rubble(row) else 0
    bm.to_mesh(body.data)
    body.data.update()
    scene.render.filepath = str(out.with_name(out.name + "-rubble.png"))
    bpy.ops.render.render(write_still=True)
    rubble = [row for row in rows if is_rubble(row)]
    rubble.sort(key=lambda row: -row["extent"])
    print("YXZ_SHARDS %s" % out)
    print("YXZ_RUBBLE_COUNT %d" % len(rubble))
    for row in rubble[:60]:
        print(
            "  rubble %d faces=%d extent=%.4f len=%.4f wid=%.4f elong=%.3f"
            " fill=%.3f centre=%s"
            % (
                row["id"], row["faces"], row["extent"], row["length"],
                row["width"], row["elongation"], row["fill"], row["centre"],
            )
        )


if __name__ == "__main__":
    main()
