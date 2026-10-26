"""The crown of the head with its triangles drawn on, so the shape of
the defect can be read rather than guessed at.

Usage:
  blender -b -P scripts/render_yxz_wire.py -- \
    --glb <glb> --out <dir> [--size 1200] [--distance 0.55]
"""

from __future__ import annotations

import sys
from pathlib import Path

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
    parts = value_after("--centre", "0.038,-0.001,0.094").split(",")
    centre = Vector([float(v) for v in parts])
    size = int(value_after("--size", "1200"))
    distance = float(value_after("--distance", "0.55"))
    thickness = float(value_after("--thickness", "0.0016"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene

    for stray in [o for o in scene.objects
                  if o.type == "MESH" and not o.data.materials]:
        name = stray.name
        mesh = stray.data
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        print("YXZ_DROPPED_IMPORTER_HELPER " + name)

    body = None
    for obj in scene.objects:
        if obj.type == "MESH" and obj.name.startswith("tripo"):
            body = obj
    if body is None:
        meshes = [o for o in scene.objects if o.type == "MESH"]
        body = max(meshes, key=lambda o: len(o.data.vertices))
    print("YXZ_WIRE body=" + body.name + " verts=%d" % len(body.data.vertices))

    # Everything but the body is hidden, so only the shell is drawn.
    for obj in scene.objects:
        if obj.type == "MESH" and obj is not body:
            obj.hide_render = True

    solid = bpy.data.materials.new("solid")
    solid.use_nodes = True
    bsdf = solid.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.80, 0.82, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.7
    body.data.materials.clear()
    body.data.materials.append(solid)

    wire = body.modifiers.new("wire", "WIREFRAME")
    wire.thickness = thickness
    wire.use_replace = False
    wire.use_even_offset = True
    wire.material_offset = 1

    lines = bpy.data.materials.new("lines")
    lines.use_nodes = True
    bsdf = lines.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.05, 0.12, 0.22, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.8
    body.data.materials.append(lines)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "PERSP"
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.93, 0.94, 0.95, 1.0)
    scene.world = world

    for name, energy, size_light, offset in (
        ("key", 90.0, 1.4, Vector((0.9, -0.7, 0.8))),
        ("fill", 26.0, 2.4, Vector((-0.6, -1.4, 0.2))),
        ("rim", 34.0, 1.0, Vector((-0.4, 1.2, 0.7))),
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
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.engine = "BLENDER_EEVEE"

    views = {
        "crown": (Vector((0.34, -0.30, 0.90)), Vector((0.0, 0.0, 0.16))),
        "brow": (Vector((0.80, -0.34, 0.52)), Vector((0.0, 0.0, 0.14))),
        "front": (Vector((1.0, 0.0, 0.10)), Vector((0.0, 0.0, 0.0))),
    }
    for name, (stand, look) in views.items():
        cam.location = centre + stand.normalized() * distance
        target = centre + look
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam_data.sensor_width = 36.0
        cam_data.lens = (distance / 0.45) * 18.0
        scene.render.filepath = str(out / f"wire-{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_WIRE_VIEW " + str(out / f"wire-{name}.png"))


if __name__ == "__main__":
    main()
