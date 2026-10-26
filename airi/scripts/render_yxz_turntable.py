"""Render orthographic front/side/back views of a YXZ GLB for visual review.

  blender -b -P scripts/render_yxz_turntable.py -- \
    --glb <path> --out <dir> [--hide-face-controls] [--textured]

 Workbench is the default so it needs no GPU and no image textures, which keeps
 the turnaround fast enough to run on every rig change.  `--textured` switches
 to EEVEE so the baked face texture is visible, which is what the eye and mouth
 work has to line up with.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out_dir = Path(value_after("--out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    hide_face = "--hide-face-controls" in sys.argv
    textured = "--textured" in sys.argv
    # az=90 puts the camera on +X, which is the direction the character faces.
    only_front = "--front-only" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE" if textured else "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1080 if textured else 720
    scene.render.resolution_y = 1350 if textured else 900
    scene.render.film_transparent = False
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE" if textured else "MATERIAL"
    shading.show_cavity = True
    if textured:
        shading.show_shadows = False
        shading.show_cavity = False
        # A background render has no viewport shading, so EEVEE needs real
        # lights or every pixel comes back black.
        world = bpy.data.worlds.new("YXZWorld")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (
            0.055,
            0.06,
            0.075,
            1.0,
        )
        world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
        scene.world = world
        sun_data = bpy.data.lights.new("YXZSun", type="SUN")
        sun_data.energy = 3.2
        sun = bpy.data.objects.new("YXZSun", sun_data)
        sun.rotation_euler = (math.radians(58), 0.0, math.radians(35))
        scene.collection.objects.link(sun)

    meshes = [o for o in scene.objects if o.type == "MESH"]
    if hide_face:
        for obj in meshes:
            if obj.name.startswith("YXZ_Face"):
                obj.hide_render = True

    # Frame everything: the asset is Z-up with roughly unit height.
    deps = bpy.context.evaluated_depsgraph_get()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in meshes:
        if obj.hide_render:
            continue
        ev = obj.evaluated_get(deps)
        for corner in ev.bound_box:
            world = ev.matrix_world @ __import__("mathutils").Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], world[i])
                hi[i] = max(hi[i], world[i])
    center = [(lo[i] + hi[i]) / 2 for i in range(3)]
    height = max(hi[i] - lo[i] for i in range(3)) or 1.0

    focus = bpy.data.objects.new("Focus", None)
    focus.location = center
    scene.collection.objects.link(focus)

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.12
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    track = cam.constraints.new("TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    distance = height * 3
    if textured:
        # Fill from the camera side so the baked face reads clearly.
        fill_data = bpy.data.lights.new("YXZFill", type="AREA")
        fill_data.energy = height * height * 260.0
        fill_data.size = height * 3.0
        fill = bpy.data.objects.new("YXZFill", fill_data)
        fill.location = (center[0] + distance * 0.8, center[1], center[2] + height * 0.3)
        fill.rotation_euler = (math.radians(72), 0.0, math.radians(90))
        scene.collection.objects.link(fill)
    views = [("face", 90)] if only_front else [
        ("front", 0),
        ("side", 90),
        ("back", 180),
        ("three_quarter", 35),
    ]
    for label, azimuth in views:
        a = math.radians(azimuth)
        cam.location = (
            center[0] + math.sin(a) * distance,
            center[1] - math.cos(a) * distance,
            center[2] + height * 0.06,
        )
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"yxz_{label}.png")
        bpy.ops.render.render(write_still=True)
        print(f"YXZ_RENDER {scene.render.filepath}")


if __name__ == "__main__":
    main()
