"""Pick a set of faces on the YXZ head and look at what was picked.

The scan tore the helmet open at the back of the crown and left the torn
pieces standing up like flaps.  Those flaps are what make the character
read as broken rather than as a model.

The flaps are found by where they are, not by how they look: they are
the geometry at the very top of the head, on the back of the crown, out
to the sides.  A rule that picks them is only useful if the picture
agrees with it, so the picked faces are drawn in magenta and the model
is rendered from the front.

Usage:
  blender -b -P scripts/select_yxz_faces.py -- \
    --glb <glb> --out <png> [--rule flap] [--yaw 0] [--pitch 0] [--size 900]
"""

from __future__ import annotations

import json
import math
import os
import sys

import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def flat_material(name, colour):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = colour
    shader.inputs["Roughness"].default_value = 0.6
    return material


def setup_world():
    world = bpy.data.worlds.new("probe")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (0.06, 0.07, 0.09, 1.0)
    background.inputs[1].default_value = 1.0

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key_object = bpy.data.objects.new("key", key)
    bpy.context.scene.collection.objects.link(key_object)
    key_object.rotation_euler = (0.9, 0.2, 0.4)
    fill = bpy.data.lights.new("fill", type="AREA")
    fill.energy = 60.0
    fill.size = 2.0
    fill_object = bpy.data.objects.new("fill", fill)
    bpy.context.scene.collection.objects.link(fill_object)
    fill_object.location = Vector((-1.2, -1.6, 0.68))
    fill_object.rotation_euler = (1.1, 0.0, -0.6)

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            bpy.context.scene.render.engine = engine
            break
        except TypeError:
            continue
    bpy.context.view_layer.update()


def flap_faces(body):
    """The torn sheets standing up at the back of the crown."""
    picked = []
    for polygon in body.data.polygons:
        x, y, z = polygon.center
        # Blender is Z up and the character faces -Y, so the back of the
        # head is +Y and the crown is high Z.
        if z < 0.29:
            continue
        if y < 0.02:
            continue
        if abs(x) < 0.10:
            continue
        picked.append(polygon.index)
    return picked


def polygon_faces(body, camera, scene, polygons, size):
    """The faces whose centre lands inside a polygon of the render."""
    from bpy_extras.object_utils import world_to_camera_view
    picked = []
    for polygon in body.data.polygons:
        projected = world_to_camera_view(scene, camera, body.matrix_world @ polygon.center)
        x = projected.x * size
        y = (1.0 - projected.y) * size
        for outline in polygons:
            if point_in_polygon(x, y, outline):
                picked.append(polygon.index)
                break
    return picked


def point_in_polygon(x, y, outline):
    inside = False
    count = len(outline)
    for index in range(count):
        x0, y0 = outline[index]
        x1, y1 = outline[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            crossing = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if crossing > x:
                inside = not inside
    return inside


def main():
    source = value_after("--glb")
    out = value_after("--out", "docs/yxz-diag/select.png")
    rule = value_after("--rule", "flap")
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

    outlines = []
    triangle_file = value_after("--tris")
    for raw in sys.argv[1:]:
        if raw.startswith("polygon="):
            outline = []
            for pair in raw[len("polygon="):].split(";"):
                if not pair:
                    continue
                px, py = pair.split(",")
                outline.append((float(px), float(py)))
            if len(outline) >= 3:
                outlines.append(outline)

    camera = None
    if outlines:
        scene = bpy.context.scene
        data = bpy.data.cameras.new("head")
        data.type = "ORTHO"
        data.ortho_scale = scale
        camera = bpy.data.objects.new("head", data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        base = Vector((0.0, -1.0, 0.0))
        turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
        camera.location = center + turned * (distance * math.cos(pitch))
        camera.location.z += distance * math.sin(pitch)
        look = (center - camera.location).normalized()
        camera.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        picked = polygon_faces(body, camera, scene, outlines, size)
    elif triangle_file:
        with open(triangle_file, "r", encoding="utf8") as handle:
            picked = json.load(handle)
        print("YXZ_SELECT mesh_polygons=%d" % len(body.data.polygons))
    else:
        picked = flap_faces(body)
    print("YXZ_SELECT rule=%s faces=%d" % (rule, len(picked)))
    if picked:
        points = [body.data.polygons[index].center for index in picked]
        print("YXZ_SELECT bbox " + json.dumps({
            "low": [round(min(p[i] for p in points), 4) for i in range(3)],
            "high": [round(max(p[i] for p in points), 4) for i in range(3)],
        }))

    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.62, 0.64, 0.68, 1.0)))
    body.data.materials.append(flat_material("picked", (0.95, 0.08, 0.35, 1.0)))
    chosen = set(picked)
    for polygon in body.data.polygons:
        polygon.material_index = 1 if polygon.index in chosen else 0
    body.data.update()

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    if camera is None:
        data = bpy.data.cameras.new("head")
        data.type = "ORTHO"
        data.ortho_scale = scale
        camera = bpy.data.objects.new("head", data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        base = Vector((0.0, -1.0, 0.0))
        turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
        camera.location = center + turned * (distance * math.cos(pitch))
        camera.location.z += distance * math.sin(pitch)
        look = (center - camera.location).normalized()
        camera.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_SELECT_RENDER " + out)


if __name__ == "__main__":
    main()
