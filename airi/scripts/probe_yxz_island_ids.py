"""
 * Which shell is that?  A false colour map of every loose piece.
 *
 * The head has a scatter of dark triangles on the crown that nothing in
 * the texture accounts for, and the only way to know which piece of
 * geometry they are is to give every piece its own colour and look.
 *
 * So the shell is rendered twice from the same camera: once with its own
 * textures, and once with every shell painted a colour of its own.  The
 * two renders are then read pixel by pixel -- the dark triangle in the
 * first one and the flat colour in the second one are the same triangle,
 * and the colour names the shell.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_island_ids.py -- --glb <glb> \
     --centre x,y,z --scale s --out <prefix>
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
    # The order of the shells has to be the same on every run, because
    # the number is what a second script uses to name a shell.  A set of
    # faces is walked in whatever order the interpreter hands them over,
    # which changes from run to run, so the shells are put back in order
    # by the lowest face they own.
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def colour_for(number):
    """A colour nothing else uses, so a pixel names exactly one shell."""
    import random

    rng = random.Random(number * 7919)
    return (rng.random(), rng.random(), rng.random())


def setup_camera(scene, centre, scale, yaw, pitch, size):
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


def background(scene, colour):
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    node = world.world.node_tree.nodes["Background"] if hasattr(world, "world") else world.node_tree.nodes["Background"]
    node.inputs[0].default_value = (colour[0], colour[1], colour[2], 1.0)
    node.inputs[1].default_value = 1.0
    scene.world = world


def lights(scene):
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


def main():
    glb = value_after("--glb")
    out = Path(value_after("--out", "docs/yxz-diag/ids"))
    out.parent.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(p) for p in value_after("--centre", "0.19,0,0.30").split(",")])
    scale = float(value_after("--scale", "0.30"))
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
    body_group = max(groups, key=len)

    scene = bpy.context.scene
    setup_camera(scene, centre, scale, yaw, pitch, size)
    background(scene, (0.09, 0.10, 0.13))
    lights(scene)

    # The textured pass, exactly as the page draws it.
    scene.render.filepath = str(out.with_name(out.name + "-textured.png"))
    bpy.ops.render.render(write_still=True)

    # Optionally paint some shells in a colour of their own over the
    # textured pass, so a shell that was named by the join can be seen
    # where it actually is rather than only counted.
    highlight = value_after("--highlight")
    if highlight:
        wanted = {int(piece) for piece in highlight.split(",") if piece.strip()}
        marker = bpy.data.materials.new("highlight")
        marker.use_nodes = True
        tree = marker.node_tree
        for node in list(tree.nodes):
            if node.type != "OUTPUT_MATERIAL":
                tree.nodes.remove(node)
        output = tree.nodes["Material Output"]
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)
        tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
        body.data.materials.append(marker)
        slot = len(body.data.materials) - 1
        for number, group in enumerate(groups):
            if number not in wanted:
                continue
            for face in group:
                face.material_index = slot
        # The faces live in the bmesh, and the mesh only learns about the
        # new slot when the bmesh is written back to it.
        bm.to_mesh(body.data)
        body.data.update()
        scene.render.filepath = str(out.with_name(out.name + "-marked.png"))
        bpy.ops.render.render(write_still=True)

    # The false colour pass: every shell gets a colour nothing else has.
    # The tone map has to come off for this one: a filmic curve would
    # bend every colour on its way to the screen, and then the colour
    # that came out would not be the colour that went in.
    previous_transform = scene.view_settings.view_transform
    previous_look = scene.view_settings.look
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    # The shell is drawn with the material it came with, and that
    # material is single sided: a face turned away from the camera is
    # not drawn at all.  The false colour pass has to be turned the
    # same way, or it shows pieces of the model that nobody can see
    # and the whole diagnosis is of a model that is not there.
    cull = "--cull" in sys.argv

    body_material = bpy.data.materials.new("body_marker")
    body_material.use_nodes = True
    tree = body_material.node_tree
    for node in list(tree.nodes):
        if node.type != "OUTPUT_MATERIAL":
            tree.nodes.remove(node)
    output = tree.nodes["Material Output"]
    emit = tree.nodes.new("ShaderNodeEmission")
    # Magenta: a colour no random island is likely to land on, so a
    # magenta pixel is the body and anything else is a loose piece.
    emit.inputs["Color"].default_value = (1.0, 0.0, 1.0, 1.0)
    emit.inputs["Strength"].default_value = 1.0
    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    body_material.use_backface_culling = cull
    body.data.materials.clear()
    body.data.materials.append(body_material)
    for face in body_group:
        face.material_index = 0
    for number, group in enumerate(groups):
        if group is body_group:
            continue
        material = bpy.data.materials.new("island_%d" % number)
        material.use_nodes = True
        tree = material.node_tree
        for node in list(tree.nodes):
            if node.type != "OUTPUT_MATERIAL":
                tree.nodes.remove(node)
        output = tree.nodes["Material Output"]
        # Unlit, so the pixel that comes out is the colour that went in.
        # With a lit material the shade would have to be undone before the
        # colour could be matched, and then the match would be a guess.
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = (*colour_for(number), 1.0)
        emit.inputs["Strength"].default_value = 1.0
        tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
        material.use_backface_culling = cull
        body.data.materials.append(material)
        for face in group:
            face.material_index = len(body.data.materials) - 1
    bm.to_mesh(body.data)
    body.data.update()
    scene.render.filepath = str(out.with_name(out.name + "-ids.png"))
    bpy.ops.render.render(write_still=True)
    scene.view_settings.view_transform = previous_transform
    scene.view_settings.look = previous_look

    # Everything about every shell goes into the one file, so that nothing
    # has to be read across from another run: the number of a shell is
    # only meaningful together with the picture of it, and the picture and
    # the number are written down together here.
    uv_layer = bm.loops.layers.uv.active
    shells_info = []
    for number, group in enumerate(groups):
        points = [vert.co for face in group for vert in face.verts]
        uvs = [
            (loop[uv_layer].uv.x, loop[uv_layer].uv.y)
            for face in group
            for loop in face.loops
        ]
        shells_info.append({
            "id": number,
            "faces": len(group),
            "zMin": round(min(p.z for p in points), 4),
            "zMax": round(max(p.z for p in points), 4),
            "uvLow": [round(min(u[0] for u in uvs), 4), round(min(u[1] for u in uvs), 4)],
            "uvHigh": [round(max(u[0] for u in uvs), 4), round(max(u[1] for u in uvs), 4)],
        })
    # Everything about every shell goes into the one file, so that nothing
    # has to be read across from another run: the number of a shell is
    # only meaningful together with the picture of it, and the picture and
    # the number are written down together here.
    uv_layer = bm.loops.layers.uv.active
    shells_info = []
    for number, group in enumerate(groups):
        points = [vert.co for face in group for vert in face.verts]
        uvs = [
            (loop[uv_layer].uv.x, loop[uv_layer].uv.y)
            for face in group
            for loop in face.loops
        ]
        shells_info.append({
            "id": number,
            "faces": len(group),
            "zMin": round(min(p.z for p in points), 4),
            "zMax": round(max(p.z for p in points), 4),
            "uvLow": [round(min(u[0] for u in uvs), 4), round(min(u[1] for u in uvs), 4)],
            "uvHigh": [round(max(u[0] for u in uvs), 4), round(max(u[1] for u in uvs), 4)],
        })
    bm.free()
    with open(str(out.with_name(out.name + ".json")), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "bodyFaces": len(body_group),
                "bodyId": groups.index(body_group),
                "shells": len(groups),
                "colours": {str(number): colour_for(number) for number in range(len(groups))},
                "info": shells_info,
            },
            handle,
        )
    print("YXZ_IDS %s" % out)


main()
