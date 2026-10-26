"""Render a rigged YXZ GLB in a set of test poses to check the skin.

A rig can have correct-looking bones and still tear at the shoulders or collapse
at the elbows, and that is only visible in a render.  Each pose is a list of
bone -> (axis, degrees) rotations applied in the armature's rest frame.

  blender -b -P scripts/render_yxz_poses.py -- \
    --glb <path> --out <dir> [--textured]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


X = Vector((1, 0, 0))
Y = Vector((0, 1, 0))
Z = Vector((0, 0, 1))

# The exported asset faces -Y with up +Z, so Z yaw turns the head left/right,
# X pitches it, and a raised arm pointing along +X lifts by turning around Y.
POSES = {
    "rest": {},
    "head_turn": {
        "head": (Z, 9), "neck": (Z, 4), "upperChest": (Z, 2),
        "leftEye": (Z, -10), "rightEye": (Z, -10),
    },
    "head_tilt": {
        "head": (X, -9), "neck": (X, -4),
        "leftEye": (X, 8), "rightEye": (X, 8),
    },
    # Gaze extremes, at the limits the VRM lookAt range maps to.  The iris is
    # a flat cap on a flat visor, so its rim swings IRIS_R * sin(angle) out of
    # plane and has to stay inside the sclera clearance; these are the angles
    # that constraint is actually sized for.
    "gaze_out": {"leftEye": (Z, 16), "rightEye": (Z, 16)},
    "gaze_in": {"leftEye": (Z, -16), "rightEye": (Z, -16)},
    "gaze_up": {"leftEye": (X, -8), "rightEye": (X, -8)},
    "gaze_down": {"leftEye": (X, 8), "rightEye": (X, 8)},
    "arm_wave": {
        "leftShoulder": (Z, -14),
        "leftUpperArm": (Y, -26),
        "leftLowerArm": (Y, -34),
        "leftHand": (Z, 22),
        "head": (Z, 10),
    },
    "arm_forward": {
        "leftUpperArm": (Z, 22),
        "leftLowerArm": (Z, 18),
        "rightUpperArm": (Z, -14),
        "spine": (Z, -6),
    },
    "leg_lift": {
        "leftUpperLeg": (X, 26), "leftLowerLeg": (X, -34),
        "leftFoot": (X, 12), "hips": (Y, 4),
    },
    "crouch": {
        "leftUpperLeg": (X, 34), "rightUpperLeg": (X, 34),
        "leftLowerLeg": (X, -62), "rightLowerLeg": (X, -62),
        "leftFoot": (X, 26), "rightFoot": (X, 26),
        "spine": (X, 8), "upperChest": (X, 6),
    },
    "wing_flare": {
        "wing.L": (Z, 26), "wing.R": (Z, -26),
        "upperChest": (X, -6),
    },
}


def main() -> None:
    glb = value_after("--glb")
    out_dir = Path(value_after("--out"))
    textured = "--textured" in sys.argv
    head_only = "--head" in sys.argv
    hidden = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--hide=")]
    morphs = []
    for arg in sys.argv:
        if arg.startswith("--morph="):
            name, _, amount = arg.split("=", 2)[1].partition(":")
            morphs.append((name, float(amount or 1)))
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene
    arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
    if arm is None:
        # An unrigged asset can still be rendered from the same camera, which
        # is how the rigged result is compared against the source.
        arm = None
    else:
        # The exported asset carries the body clips, and Blender restores one
        # of them onto the armature on import.  The test poses have to start
        # from the rest pose, so the animation is detached and every channel
        # cleared.
        if arm.animation_data:
            arm.animation_data_clear()

    scene.render.engine = "BLENDER_EEVEE" if textured else "BLENDER_WORKBENCH"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1125
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE" if textured else "MATERIAL"
    shading.show_cavity = True
    shading.show_shadows = False

    meshes = [o for o in scene.objects if o.type == "MESH"]
    # The rig stores the asset in the exported frame (facing -Y).  Rendering
    # the raw Tripo asset through the same rotation is what makes the two
    # comparable pixel for pixel.
    for arg in sys.argv:
        if arg.startswith("--rotate-z="):
            import bpy as _bpy
            from mathutils import Matrix as _Matrix
            angle = math.radians(float(arg.split("=", 1)[1]))
            for obj in meshes:
                obj.data.transform(_Matrix.Rotation(angle, 4, "Z"))
                obj.data.update()
    for obj in meshes:
        if any(obj.name.startswith(prefix) for prefix in hidden):
            obj.hide_render = True
    deps = bpy.context.evaluated_depsgraph_get()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in meshes:
        ev = obj.evaluated_get(deps)
        for corner in ev.bound_box:
            world = ev.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], world[i])
                hi[i] = max(hi[i], world[i])
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

    if textured:
        world = bpy.data.worlds.new("W")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.07, 1)
        scene.world = world
        sun_data = bpy.data.lights.new("Sun", type="SUN")
        sun_data.energy = 3.2
        sun = bpy.data.objects.new("Sun", sun_data)
        sun.rotation_euler = (math.radians(58), 0, math.radians(35))
        scene.collection.objects.link(sun)

    distance = height * 3
    # az=90 looks along +X in the old frame; the asset now faces -Y, so the
    # camera sits on -Y to see the face.
    for name, pose in POSES.items():
        if arm is None and name != "rest":
            continue
        if arm is not None:
            for bone in arm.pose.bones:
                bone.rotation_mode = "QUATERNION"
                bone.rotation_quaternion = Quaternion((1, 0, 0, 0))
                bone.location = (0.0, 0.0, 0.0)
                bone.scale = (1.0, 1.0, 1.0)
            for bone_name, (axis, degrees) in pose.items():
                pb = arm.pose.bones.get(bone_name)
                if pb is None:
                    print("YXZ_POSE_WARN missing bone " + bone_name)
                    continue
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = Quaternion(axis, math.radians(degrees))
        for morph_name, amount in morphs:
            for obj in meshes:
                keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
                if morph_name in keys:
                    keys[morph_name].value = amount
        bpy.context.view_layer.update()

        views = [("face", Vector((0, -1, 0)))]
        if not head_only:
            views.append(("side", Vector((1, 0, 0))))
        for view, offset in views:
            cam.location = Vector(center) + offset * distance
            cam.location.z += height * 0.05
            bpy.context.view_layer.update()
            scene.render.filepath = str(out_dir / f"pose_{name}_{view}.png")
            bpy.ops.render.render(write_still=True)
            print("YXZ_POSE_RENDER " + scene.render.filepath)


if __name__ == "__main__":
    main()
