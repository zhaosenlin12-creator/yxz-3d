"""Look at the crown of the head with its parts coloured by kind.

The head in the scan is made of more than one surface: the shell that
fits the head, and a sheet that was folded back over it.  From a
render they look the same, so this paints them apart - grey for the
shell that faces out, red for the surfaces that face in, blue for the
surfaces that stand off the ball of the head.

Usage:
  blender -b -P scripts/render_yxz_crown_debug.py -- \
    --glb <glb> --out <dir> [--centre 0,0.064,0]
"""

from __future__ import annotations

import sys
from pathlib import Path

import math

import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    out.mkdir(parents=True, exist_ok=True)
    parts = value_after("--centre", "0,0,0.064").split(",")
    local_centre = Vector([float(v) for v in parts])
    radius = float(value_after("--radius", "0.3193"))
    size = int(value_after("--size", "700"))
    distance = float(value_after("--distance", "0.62"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene

    for stray in [o for o in scene.objects if o.type == "MESH" and not o.data.materials]:
        name = stray.name
        mesh = stray.data
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(mesh)

    body = None
    for obj in scene.objects:
        if obj.type == "MESH" and obj.name.startswith("tripo"):
            body = obj
    if body is None:
        meshes = [o for o in scene.objects if o.type == "MESH"]
        body = max(meshes, key=lambda o: len(o.data.vertices))

    shell = bpy.data.materials.new("shell")
    shell.use_nodes = True
    bsdf = shell.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.82, 0.83, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6

    inward = bpy.data.materials.new("inward")
    inward.use_nodes = True
    bsdf = inward.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.85, 0.12, 0.12, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6

    proud = bpy.data.materials.new("proud")
    proud.use_nodes = True
    bsdf = proud.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.10, 0.35, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6

    body.data.materials.clear()
    for mat in (shell, inward, proud):
        body.data.materials.append(mat)

    counts = [0, 0, 0]
    stats = []
    for poly in body.data.polygons:
        centroid = poly.center
        offset = centroid - local_centre
        length = offset.length
        if length < 1e-6:
            poly.material_index = 0
            counts[0] += 1
            continue
        direction = offset / length
        elevation = math.degrees(math.asin(max(-1.0, min(1.0, direction.z))))
        facing = poly.normal.dot(direction)
        if elevation > 8.0 and length > radius + 0.008:
            poly.material_index = 2
            counts[2] += 1
        elif elevation > 8.0 and facing < 0.0:
            poly.material_index = 1
            counts[1] += 1
        else:
            poly.material_index = 0
            counts[0] += 1
        stats.append((length, elevation, facing))
    arr = sorted(stats)
    print("YXZ_DEBUG polys=%d  len %.4f..%.4f  el %.1f..%.1f  facing %.2f..%.2f" % (
        len(stats), arr[0][0], arr[-1][0],
        min(s[1] for s in stats), max(s[1] for s in stats),
        min(s[2] for s in stats), max(s[2] for s in stats)))
    print("YXZ_DEBUG faces shell=%d inward=%d proud=%d" % tuple(counts))

    # The importer keeps the mesh in the file's own frame and rotates
    # the object instead, so the camera has to work in world space.
    centre = body.matrix_world @ local_centre
    print("YXZ_DEBUG head world %s" % [round(v, 4) for v in centre])

    cam_data = bpy.data.cameras.new("crown")
    cam = bpy.data.objects.new("crown", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.92, 0.93, 0.95, 1.0)
    scene.world = world

    for name, energy, size_light, offset in (
        ("key", 60.0, 1.0, Vector((0.6, -0.5, 0.6))),
        ("fill", 20.0, 2.0, Vector((-0.6, -1.0, 0.2))),
    ):
        light = bpy.data.lights.new(name, type="AREA")
        light.energy = energy
        light.size = size_light
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.location = centre + offset
        obj.rotation_euler = (centre - obj.location).to_track_quat("-Z", "Y").to_euler()

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.engine = "BLENDER_EEVEE"

    views = {
        "crown": Vector((0.10, -0.30, 0.95)),
        "front": Vector((-0.10, -0.95, 0.30)),
        "back": Vector((-0.10, 0.95, 0.30)),
        "side": Vector((0.90, -0.30, 0.32)),
    }
    for name, stand in views.items():
        cam.location = centre + stand.normalized() * distance
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam_data.sensor_width = 36.0
        cam_data.lens = (distance / 0.30) * 18.0
        scene.render.filepath = str(out / f"crown-{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_DEBUG_VIEW " + str(out / f"crown-{name}.png"))


if __name__ == "__main__":
    main()
