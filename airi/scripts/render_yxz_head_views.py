"""Close photographs of the head, from the model file.

The stage shows the character at the size a person sees it, which is the
right size for the character and the wrong size for the question.  A
torn edge on the helmet is four millimetres across; at the size it is
meant to be seen that is a quarter of a pixel, and it only becomes a
question at the size it is wrong.

So this is the head alone, at the size the head is wrong, from the
angles the head is wrong from.  The model's own texture is kept, because
the texture is half of what is being judged.

Usage:
  blender -b -P scripts/render_yxz_head_views.py -- \
    --glb <glb> --out <dir> [--centre 0.038,-0.001,0.094] \
    [--size 900] [--flat]
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
    size = int(value_after("--size", "900"))
    distance = float(value_after("--distance", "1.05"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene

    # The importer leaves a unit sphere behind for VRM files, and a unit
    # sphere at the origin fills the frame.
    for stray in [o for o in scene.objects
                  if o.type == "MESH" and not o.data.materials]:
        name = stray.name
        mesh = stray.data
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        print("YXZ_DROPPED_IMPORTER_HELPER " + name)

    if "--flat" in sys.argv:
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
                0.86, 0.87, 0.89, 1.0)
            material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.65
            obj.data.materials.append(material)

    cam_data = bpy.data.cameras.new("head")
    cam_data.type = "PERSP"
    cam = bpy.data.objects.new("head", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.90, 0.92, 0.94, 1.0)
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

    # Where to stand, and what to look at.
    views = {
        "front": (Vector((1.0, 0.0, 0.10)), Vector((0.0, 0.0, 0.0)), 0.62),
        "brow": (Vector((0.80, -0.34, 0.52)), Vector((0.0, 0.0, 0.14)), 0.40),
        "quarter": (Vector((0.72, -0.62, 0.18)), Vector((0.0, 0.0, 0.02)), 0.55),
        "ear": (Vector((0.16, -0.95, 0.06)), Vector((0.0, 0.0, 0.0)), 0.55),
        "crown": (Vector((0.34, -0.30, 0.90)), Vector((0.0, 0.0, 0.16)), 0.46),
    }
    for name, (stand, look, frame) in views.items():
        cam.location = centre + stand.normalized() * distance
        target = centre + look
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        # The frame is set by how much of the head the shot is asked to
        # show, so the shots are comparable with each other and with the
        # next build.
        cam_data.sensor_width = 36.0
        cam_data.lens = (distance / frame) * 18.0
        scene.render.filepath = str(out / f"head-{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_HEAD_VIEW " + str(out / f"head-{name}.png"))


if __name__ == "__main__":
    main()
