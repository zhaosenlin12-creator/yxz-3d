"""Add a restrained, shape-preserving hand gesture to YXZ_Speaking.

The source character is a single skinned mesh. This script only adds rotation
keys to the existing armature action; it never edits vertices, weights or
object scale. The gesture is intentionally small so the feet stay planted and
the Tripo silhouette does not stretch during speech.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion


def add_quaternion_keys(action: bpy.types.Action, armature: bpy.types.Object, bone_name: str, values: tuple[tuple[int, float], ...]) -> None:
    """Replace the existing static quaternion track with a local-Z gesture."""
    path = f'pose.bones["{bone_name}"].rotation_quaternion'
    curves = [action.fcurve_ensure_for_datablock(armature, path, index=index, group_name=bone_name) for index in range(4)]
    bpy.context.scene.frame_set(1)
    base = armature.pose.bones[bone_name].rotation_quaternion.copy()
    for curve in curves:
        curve.keyframe_points.clear()
    for frame, angle in values:
        delta = Quaternion((0.0, 0.0, 1.0), angle)
        result = base @ delta
        for index, curve in enumerate(curves):
            curve.keyframe_points.insert(frame, result[index], options={"FAST"})
    for curve in curves:
        curve.update()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("YXZ armature was not found")
    action = bpy.data.actions.get("YXZ_Speaking")
    if action is None:
        raise RuntimeError("YXZ_Speaking action was not found")

    # Three relaxed gestures over the same 4-second clip. Z is the arm's
    # existing local bend axis, verified against the authored Success clip.
    armature.animation_data_create()
    armature.animation_data.action = action
    add_quaternion_keys(action, armature, "upper_arm.R", ((1, -0.035), (30, 0.07), (60, -0.03), (90, 0.07), (120, -0.035)))
    add_quaternion_keys(action, armature, "forearm.R", ((1, -0.02), (30, 0.05), (60, -0.015), (90, 0.05), (120, -0.02)))
    add_quaternion_keys(action, armature, "hand.R", ((1, -0.05), (30, 0.16), (60, -0.04), (90, 0.16), (120, -0.05)))
    armature.animation_data.action = None

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_apply=False,
        export_animations=True,
        export_skins=True,
        export_morph=True,
        export_nla_strips=True,
        export_anim_single_armature=True,
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
    )
    print(f"speaking gesture written to {args.output}")


if __name__ == "__main__":
    main()
