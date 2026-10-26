"""Minimal reproduction of the YXZ clip authoring path.

The full build takes a minute and drags a mesh through it, so the clip
maths gets its own tiny scene: a root bone, a child bone and a helper bone
child of the root, authored the same way `build_yxz_clips.py` does.  It
prints the fcurve values, the evaluated pose and the exported glTF channels
so the point where the motion is lost is visible.

  blender -b -P scripts/probe_yxz_clip_math.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_yxz_clips import Clip  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "yxz-rig-review" / "clip_math.glb"


def build_armature():
    arm_data = bpy.data.armatures.new("Probe")
    arm = bpy.data.objects.new("Probe", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    spec = [
        ("hips", (0.0, -0.04, -0.19), (0.0, -0.04, -0.13), None),
        ("spine", (0.0, -0.04, -0.13), (0.0, -0.04, -0.06), "hips"),
        ("halo", (-0.20, 0.0, 0.41), (-0.16, 0.0, 0.48), "hips"),
    ]
    created = {}
    for name, head, tail, parent in spec:
        bone = arm_data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        if parent:
            bone.parent = created[parent]
            bone.use_connect = False
        created[name] = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    for pose_bone in arm.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    return arm


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = build_armature()

    clip = Clip(arm, "PROBE", 60)
    for frame in (1, 15, 30, 45, 60):
        t = (frame - 1) / 60.0
        yaw = 10.0 * math.sin(t * math.tau)
        clip.pose(frame, "hips", yaw=yaw, pitch=3.0, roll=5.0,
                  lift=0.014 * math.sin(t * math.tau))
        clip.pose(frame, "spine", yaw=yaw)
        clip.pose(frame, "halo", yaw=yaw, roll=5.0)
    clip.write()

    # What actually landed in the fcurves.
    action = bpy.data.actions["PROBE"]
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                try:
                    bag = strip.channelbag(slot)
                except Exception as error:  # noqa: BLE001
                    print(f"CHANNELBAG_FAIL {slot.identifier} {error}")
                    continue
                if bag is None:
                    continue
                for curve in bag.fcurves:
                    values = [round(k.co[1], 6) for k in curve.keyframe_points]
                    print(f"FCURVE {curve.data_path}#{curve.array_index} "
                          f"n={len(values)} {values[:8]}")

    # What the pose evaluates to at those frames.
    action_slot = arm.animation_data.action_slot
    print("SLOTS " + str([(s.identifier, s.name_display)
                          for s in action.slots]))
    print("ARM_SLOT " + str(action_slot.identifier if action_slot else None))
    arm.animation_data.action = action
    for frame in (1, 15, 30):
        bpy.context.scene.frame_set(frame)
        for bone in ("hips", "spine", "halo"):
            pb = arm.pose.bones[bone]
            print(f"POSE frame={frame} {bone} "
                  f"quat={[round(c, 6) for c in pb.rotation_quaternion]} "
                  f"loc={[round(c, 6) for c in pb.location]} "
                  f"basis_diag={[round(c, 5) for c in pb.matrix_basis.to_3x3().row[0]]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(OUT),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_yup=True,
    )
    print("EXPORTED " + str(OUT))


if __name__ == "__main__":
    main()
