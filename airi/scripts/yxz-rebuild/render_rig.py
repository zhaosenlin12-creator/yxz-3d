"""Render the rigged model and write the bone positions next to the frames.

The rig is placed by measurement, so it has to be looked at: this renders
the model from the same orthographic views the landmarks were measured in
and writes every bone's world position for each frame, so the skeleton can
be drawn over the picture and checked against the mesh.

  blender -b -P scripts/yxz-rebuild/render_rig.py -- \
      --glb .run/rig/yxz_rig.glb --out .run/pose [--clips YXZ_Wave,YXZ_Idle]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def look_at(cam, loc, target):
    cam.location = loc
    forward = (Vector(target) - Vector(loc)).normalized()
    cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()


def view_map(scene, cam, size, u_axis, v_axis):
    def px(point):
        co = world_to_camera_view(scene, cam, Vector(point))
        return (co.x * size, (1.0 - co.y) * size)

    origin = px((0.0, 0.0, 0.0))
    unit = px(u_axis)
    span = abs(unit[0] - origin[0]) or abs(unit[1] - origin[1])
    return {"pixels_per_unit": span or 1.0, "origin_px": [origin[0], origin[1]],
            "u": list(u_axis), "v": list(v_axis), "resolution": size}


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out", ".run/pose"))
    out.mkdir(parents=True, exist_ok=True)
    size = int(value_after("--size", "1100"))
    wanted = [name for name in value_after("--clips", "").split(",") if name]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    scene = bpy.context.scene

    meshes = [o for o in scene.objects if o.type == "MESH"]
    points = []
    for obj in meshes:
        points.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
    lo = Vector((min(p.x for p in points), min(p.y for p in points),
                 min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points),
                 max(p.z for p in points)))
    height = hi.z - lo.z
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2))

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.10, 0.13, 1.0)
    scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.15
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.85, 0.87, 0.9)
    scene.display.shading.show_cavity = True
    scene.render.film_transparent = False

    far = height * 2
    views = {
        "front": (Vector((centre.x, lo.y - far, centre.z)),
                  Vector((centre.x, centre.y, centre.z)),
                  (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        "side": (Vector((lo.x - far, centre.y, centre.z)),
                 Vector((centre.x, centre.y, centre.z)),
                 (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    }
    maps = {}
    for name, (loc, target, u_axis, v_axis) in views.items():
        look_at(cam, loc, target)
        maps[name] = view_map(scene, cam, size, u_axis, v_axis)

    arm = next(o for o in scene.objects if o.type == "ARMATURE")
    actions = {action.name: action for action in bpy.data.actions}
    print("YXZ_ACTIONS " + json.dumps(sorted(actions)))

    def bones_now():
        out_bones = {}
        for bone in arm.data.bones:
            head = arm.matrix_world @ bone.head_local
            tail = arm.matrix_world @ bone.tail_local
            out_bones[bone.name] = [list(head), list(tail)]
        return out_bones

    def render(tag, frame):
        scene.frame_set(frame)
        for name, (loc, target, u_axis, v_axis) in views.items():
            look_at(cam, loc, target)
            scene.render.filepath = str(out / (tag + "_" + name + ".png"))
            bpy.ops.render.render(write_still=True)

    report = {"maps": maps, "frames": {}}

    if arm.animation_data:
        arm.animation_data.action = None
        for track in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(track)
    render("rest", 1)
    report["frames"]["rest"] = {"frame": 1, "bones": bones_now()}

    for clip in wanted:
        action = actions.get(clip)
        if action is None:
            print("YXZ_NO_CLIP " + clip)
            continue
        arm.animation_data_create()
        arm.animation_data.action = action
        span = action.frame_range
        picks = sorted(set(int(round(span[0] + (span[1] - span[0]) * step / 4))
                           for step in range(5)))
        for frame in picks:
            tag = clip + "_" + str(frame)
            render(tag, frame)
            entry = {"frame": frame, "bones": bones_now()}
            report["frames"][tag] = entry
        arm.animation_data.action = None

    (out / "rig.json").write_text(json.dumps(report), encoding="utf-8")
    print("YXZ_RENDERED " + str(out / "rig.json"))


main()
