"""Render stills out of the authored YXZ clips.

Body motion cannot be judged from a rig: a clip that reads as a smooth breath
in the curve editor can still throw the arm through the torso, or leave the
head bobbing out of time with the wing.  This renders a strip of frames from
each clip so the motion can be looked at.

  blender -b -P scripts/render_yxz_clips.py -- \
    --glb <glb> --out <dir> [--clips YXZ_Idle,YXZ_Wave] [--samples 4]
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
    out_dir = Path(value_after("--out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    names = [n for n in (value_after("--clips", "") or "").split(",") if n]
    samples = int(value_after("--samples", 4))
    head_only = "--head" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene
    arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
    if arm is None:
        raise RuntimeError("no armature in the GLB")

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1125
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_cavity = True
    shading.show_shadows = False

    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.07, 1)
    scene.world = world
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.2
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (0.99, 0.0, 0.61)
    scene.collection.objects.link(sun)

    meshes = [o for o in scene.objects if o.type == "MESH"]
    deps = bpy.context.evaluated_depsgraph_get()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in meshes:
        ev = obj.evaluated_get(deps)
        for corner in ev.bound_box:
            world_corner = ev.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], world_corner[i])
                hi[i] = max(hi[i], world_corner[i])
    center = [(lo[i] + hi[i]) / 2 for i in range(3)]
    height = max(hi[i] - lo[i] for i in range(3)) or 1.0
    if head_only:
        center = [0.0, -0.02, 0.16]
        height = 0.56

    focus = bpy.data.objects.new("Focus", None)
    focus.location = center
    scene.collection.objects.link(focus)
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.15
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    track = cam.constraints.new("TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam
    distance = height * 3

    available = sorted(a.name for a in bpy.data.actions)
    print("YXZ_CLIP_ACTIONS " + str(available))
    for action in bpy.data.actions:
        if names and action.name not in names:
            continue
        arm.animation_data_create()
        arm.animation_data.action = action
        scene.frame_start = 1
        last = int(action.frame_range[1])
        scene.frame_end = last
        action.frame_end = last
        for index in range(samples):
            frame = 1 + round((last - 1) * index / max(1, samples - 1))
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            cam.location = Vector(center) + Vector((0.0, -1.0, 0.0)) * distance
            cam.location.z += height * 0.05
            bpy.context.view_layer.update()
            scene.render.filepath = str(out_dir / f"clip_{action.name}_{frame:04d}.png")
            bpy.ops.render.render(write_still=True)
            print("YXZ_CLIP_RENDER " + scene.render.filepath)
        arm.animation_data.action = None


if __name__ == "__main__":
    main()
