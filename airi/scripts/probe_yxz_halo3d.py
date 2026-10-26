"""What is actually above the character's head.

Prints the world bounds of every object in a built VRM/GLB and renders the
same view with the halo picked out in colour, so the shape of the ring and
the remains of the scan's own broken ring can be told apart.

Usage:
  blender -b -P scripts/probe_yxz_halo3d.py -- \
    --glb <file> --out <png> --yaw 90 --center 0,0,0.45 --scale 0.5
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = [min(c[i] for c in corners) for i in range(3)]
    high = [max(c[i] for c in corners) for i in range(3)]
    return [round(v, 4) for v in low], [round(v, 4) for v in high]


def main() -> None:
    glb = Path(value_after("--glb"))
    out = Path(value_after("--out", "docs/yxz-diag/halo3d.png"))
    yaw = float(value_after("--yaw", 90))
    centre = Vector([float(v) for v in value_after("--center", "0,0,0.45").split(",")])
    scale = float(value_after("--scale", 0.5))
    out.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))

    report = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        low, high = bounds(obj)
        report.append({
            "name": obj.name,
            "faces": len(obj.data.polygons),
            "low": low,
            "high": high,
        })
    report.sort(key=lambda entry: -entry["faces"])
    for entry in report:
        print("YXZ_OBJ " + json.dumps(entry))

    # Colour the halo so the ring and the scan's remains are told apart.
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        material = bpy.data.materials.new("probe_" + obj.name)
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        if obj.name == "YXZ_Halo":
            colour = (0.9, 0.05, 0.05, 1.0)
        elif obj.name == "YXZ_HaloStar":
            colour = (0.05, 0.2, 0.95, 1.0)
        else:
            colour = (0.62, 0.62, 0.62, 1.0)
        shader.inputs["Base Color"].default_value = colour
        shader.inputs["Roughness"].default_value = 0.6
        obj.data.materials.clear()
        obj.data.materials.append(material)

    camera_data = bpy.data.cameras.new("cam")
    camera = bpy.data.objects.new("cam", camera_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale
    direction = Vector((np.cos(np.radians(yaw)), np.sin(np.radians(yaw)), 0.0))
    camera.location = centre + direction * 4.0
    camera.rotation_euler = (np.radians(90), 0.0, np.radians(yaw + 90))

    light_data = bpy.data.lights.new("sun", type="SUN")
    light_data.energy = 4.0
    light = bpy.data.objects.new("sun", light_data)
    bpy.context.collection.objects.link(light)
    light.location = centre + Vector((2.0, -2.0, 3.0))
    light.rotation_euler = (np.radians(35), np.radians(10), np.radians(-35))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.filepath = str(out.resolve())
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print("YXZ_HALO3D_RENDERED " + str(out))


if __name__ == "__main__":
    main()
