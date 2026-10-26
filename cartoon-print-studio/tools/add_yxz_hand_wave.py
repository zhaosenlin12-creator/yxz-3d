"""Add a restrained wrist wave to the authored YXZ_Success action.

The source asset is kept untouched. This script writes a separate GLB so the
runtime can be rolled back without losing the original face-control model.
Only hand.R rotation is changed; no mesh vertices, scale, or skin weights are
modified.
"""

import math
import sys

import bpy
from mathutils import Quaternion


if len(sys.argv) < 3:
    raise SystemExit("usage: blender --background --python add_yxz_hand_wave.py -- INPUT OUTPUT")

input_path = sys.argv[-2]
output_path = sys.argv[-1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=input_path)

armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
if armature is None:
    raise RuntimeError("YXZ armature not found")

action = bpy.data.actions.get("YXZ_Success")
if action is None:
    raise RuntimeError("YXZ_Success action not found")

hand = armature.pose.bones.get("hand.R")
if hand is None:
    raise RuntimeError("hand.R bone not found")

armature.animation_data_create()
armature.animation_data.action = action
bpy.context.scene.frame_set(1)
base = hand.rotation_quaternion.copy()

if not len(action.layers) or not len(action.layers[0].strips) or not len(action.layers[0].strips[0].channelbags):
    raise RuntimeError("Blender action channel bag not found")

channelbag = action.layers[0].strips[0].channelbags[0]
path = 'pose.bones["hand.R"].rotation_quaternion'
curves = [fc for fc in channelbag.fcurves if fc.data_path == path]
if len(curves) != 4:
    raise RuntimeError(f"expected 4 hand rotation curves, got {len(curves)}")

for curve in curves:
    curve.keyframe_points.clear()
    curve.extrapolation = "CONSTANT"

# A small side-to-side wrist wave. The hand remains attached to the forearm;
# these are rotations only, with eased keyframes and a neutral final pose.
wave_keys = (
    (1, -0.08),
    (24, 0.20),
    (48, -0.20),
    (72, 0.20),
    (96, -0.16),
    (120, 0.0),
)
for frame, angle in wave_keys:
    # Local Y swings the palm left/right; a very small X component keeps the
    # wrist from looking mechanically flat without changing the silhouette.
    turn = Quaternion((0.0, 1.0, 0.0), angle)
    lift = Quaternion((1.0, 0.0, 0.0), angle * 0.32)
    rotation = base @ turn @ lift
    for index, curve in enumerate(curves):
        point = curve.keyframe_points.insert(frame, rotation[index], options={"FAST"})
        point.interpolation = "BEZIER"

for curve in curves:
    curve.update()

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 120
bpy.ops.export_scene.gltf(
    filepath=output_path,
    export_format="GLB",
    export_animations=True,
    export_animation_mode="ACTIONS",
    export_nla_strips=False,
    export_force_sampling=True,
    export_draco_mesh_compression_enable=True,
    export_draco_mesh_compression_level=6,
)

print("WROTE", output_path)
