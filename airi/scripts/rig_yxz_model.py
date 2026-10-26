import bpy
import math
import sys
from pathlib import Path
from mathutils import Vector


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


source = Path(value_after("--source"))
target = Path(value_after("--target"))
target.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes:
    raise RuntimeError("No mesh found in Tripo model")

armature_data = bpy.data.armatures.new("YXZ_Armature")
armature = bpy.data.objects.new("YXZ_Armature", armature_data)
bpy.context.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

def bone(name: str, head: tuple[float, float, float], tail: tuple[float, float, float], parent=None):
    result = armature_data.edit_bones.new(name)
    result.head = head
    result.tail = tail
    if parent:
        result.parent = parent
        result.use_connect = False
    return result


root = bone("root", (0, 0, -0.50), (0, 0, -0.42))
hips = bone("hips", (0, 0, -0.42), (0, 0, -0.25), root)
spine = bone("spine", (0, 0, -0.25), (0, 0, 0.08), hips)
neck = bone("neck", (0, 0, 0.08), (0, 0, 0.22), spine)
head = bone("head", (0, 0, 0.22), (0, 0, 0.50), neck)

arms = {}
legs = {}
for side, label in ((-1, "L"), (1, "R")):
    shoulder = bone(f"shoulder.{label}", (side * 0.17, 0, 0.14), (side * 0.27, 0, 0.12), spine)
    upper_arm = bone(f"upper_arm.{label}", (side * 0.27, 0, 0.12), (side * 0.38, 0, 0.02), shoulder)
    forearm = bone(f"forearm.{label}", (side * 0.38, 0, 0.02), (side * 0.39, 0, -0.15), upper_arm)
    hand = bone(f"hand.{label}", (side * 0.39, 0, -0.15), (side * 0.39, 0, -0.25), forearm)
    arms[side] = (shoulder, upper_arm, forearm, hand)
    thigh = bone(f"thigh.{label}", (side * 0.12, 0, -0.25), (side * 0.13, 0, -0.38), hips)
    shin = bone(f"shin.{label}", (side * 0.13, 0, -0.38), (side * 0.13, 0, -0.50), thigh)
    foot = bone(f"foot.{label}", (side * 0.13, 0, -0.50), (side * 0.13, 0.12, -0.50), shin)
    legs[side] = (thigh, shin, foot)

bpy.ops.object.mode_set(mode="POSE")
for pose_bone in armature.pose.bones:
    pose_bone.rotation_mode = "XYZ"
bpy.ops.object.mode_set(mode="OBJECT")

for mesh in meshes:
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    armature.select_set(True)
    # The armature must be the active object for automatic weighting.
    bpy.context.view_layer.objects.active = armature
    # Heat weights are fragile on dense single-mesh scans; envelopes are
    # deterministic and still produce a valid deforming skin for this model.
    bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
    mesh.select_set(False)
armature.select_set(False)

def add_action(name: str, action_fn):
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    armature.animation_data_create()
    # Blender 5.x uses layered Actions. Assigning the action to the armature
    # lets fcurve_ensure_for_datablock create the first layer/strip/slot.
    armature.animation_data.action = action
    action_fn(action)
    armature.animation_data.action = None
    track = armature.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 1, action)
    strip.action_frame_start = 1
    strip.action_frame_end = 120
    strip.frame_start = 1
    strip.frame_end = 120
    strip.repeat = 1

def key(action, bone_name: str, frame: int, rotation=(0.0, 0.0, 0.0), location=None):
    for axis, value in enumerate(rotation):
        path = f'pose.bones["{bone_name}"].rotation_euler'
        curve = action.fcurve_ensure_for_datablock(armature, path, index=axis, group_name=bone_name)
        curve.keyframe_points.insert(frame, value, options={"FAST"})
    if location is not None:
        path = f'pose.bones["{bone_name}"].location'
        for axis, value in enumerate(location):
            curve = action.fcurve_ensure_for_datablock(armature, path, index=axis, group_name=bone_name)
            curve.keyframe_points.insert(frame, value, options={"FAST"})

def idle(action):
    for frame, sway in ((1, -0.015), (60, 0.015), (120, -0.015)):
        key(action, "spine", frame, rotation=(0, sway, 0))
        key(action, "head", frame, rotation=(0, -sway * 1.5, 0))
        key(action, "root", frame, location=(0, 0.008 if frame == 60 else 0, 0))

def listening(action):
    for frame, tilt in ((1, -0.04), (60, -0.06), (120, -0.04)):
        key(action, "head", frame, rotation=(tilt, 0.04, 0))
        key(action, "spine", frame, rotation=(0, -0.015, 0))

def thinking(action):
    for frame, tilt in ((1, -0.06), (60, 0.04), (120, -0.06)):
        key(action, "head", frame, rotation=(0.02, tilt, 0.02))
        key(action, "upper_arm.R", frame, rotation=(0, 0, -0.12))

def speaking(action):
    for frame, sway in ((1, -0.02), (30, 0.02), (60, -0.02), (90, 0.02), (120, -0.02)):
        key(action, "head", frame, rotation=(0, sway, 0))
        key(action, "spine", frame, rotation=(0, -sway * 0.45, 0))

def success(action):
    for frame, wave in ((1, 0.0), (30, -0.32), (60, -0.18), (90, -0.32), (120, 0.0)):
        key(action, "upper_arm.R", frame, rotation=(0, 0, wave))
        key(action, "forearm.R", frame, rotation=(0, 0, wave * 0.6))
        key(action, "head", frame, rotation=(0, wave * 0.14, 0))

add_action("YXZ_Idle", idle)
add_action("YXZ_Listening", listening)
add_action("YXZ_Thinking", thinking)
add_action("YXZ_Speaking", speaking)
add_action("YXZ_Success", success)

bpy.ops.object.select_all(action="DESELECT")
for mesh in meshes:
    mesh.select_set(True)
armature.select_set(True)
bpy.context.view_layer.objects.active = armature
bpy.ops.export_scene.gltf(
    filepath=str(target),
    export_format="GLB",
    use_selection=True,
    export_materials="EXPORT",
    export_texcoords=True,
    export_normals=True,
    export_apply=False,
    export_animations=True,
    export_nla_strips=True,
    export_anim_single_armature=True,
    export_image_format="AUTO",
)
print(f"rigged model written to {target}")
