"""Author the body motion that turns the YXZ rig from a statue into a person.

AIRI's AIRI-avatar does not read as alive because of any single clip; it reads
as alive because small motion is *always* running underneath whatever the
model is saying -- breathing while idle, a weight shift while listening, a
nod per phrase while speaking.  The eye bones are deliberately absent from
these clips: `VRMLookAtQuaternionProxy` owns them, and a clip that also
wrote them would fight the gaze every frame.

Poses are authored as world-axis rotations about the bone's own head, then
converted to a basis matrix by hand.  Going through `PoseBone.matrix` would
decompose against whatever the parent happened to be doing at the time, which
makes the result depend on the order the keys happen to be written in.

The arm angles are tied to where the arm bones actually sit in the mesh, so
they are small on purpose.  The Tripo pose already has one arm up in a wave
and the other down holding a book; the rig measures those limbs instead of
assuming a neutral stance, which means the clips add *motion* to a pose
that is already there.  A big shoulder roll would swing the raised hand
behind the head, because the bone now starts at the shoulder pad rather
than at the neck.

Imported by `build_yxz_vrm.py`; the exported frame faces -Y with up +Z and
the character's own left on +X, so Z yaws, X pitches and Y rolls.
"""

from __future__ import annotations

import json
import math

import bpy
from mathutils import Matrix, Quaternion, Vector


FPS = 30
X = Vector((1.0, 0.0, 0.0))
Y = Vector((0.0, 1.0, 0.0))
Z = Vector((0.0, 0.0, 1.0))


class Clip:
    """Collects keyed bone transforms for one looping action."""

    def __init__(self, armature, name, frames):
        self.armature = armature
        self.name = name
        self.frames = frames
        self.keys = {}

    def pose(self, frame, bone, yaw=0.0, pitch=0.0, roll=0.0, lift=0.0):
        """Key one bone at one frame.

        `yaw` turns about world Z (positive looks to the character's left),
        `pitch` nods about world X, `roll` leans about world Y, and `lift`
        raises the bone along the armature's up axis.

        The rotation is authored in world axes and then conjugated into the
        bone's own frame, because a pose bone rotates about its head in bone
        space: the arm bones point diagonally, so a world yaw has to be
        carried over rather than written straight into the quaternion.
        """
        pose_bone = self.armature.pose.bones.get(bone)
        if pose_bone is None:
            print("YXZ_CLIP_WARN " + self.name + " has no bone " + bone)
            return
        rest = pose_bone.bone.matrix_local.to_3x3()
        world = (Matrix.Rotation(math.radians(yaw), 3, Z)
                 @ Matrix.Rotation(math.radians(pitch), 3, X)
                 @ Matrix.Rotation(math.radians(roll), 3, Y))
        local = rest.inverted() @ world @ rest
        # `location` lives in the bone's own frame, where +Y runs along the
        # bone.  Writing the lift straight into Z moved the hips sideways on
        # this rig, because every bone here points up the character's spine.
        # Converting world up into bone space keeps the breath vertical.
        offset = (rest.inverted() @ Vector((0.0, 0.0, 1.0))) * lift
        self.keys.setdefault(bone, {})[frame] = (
            local.to_quaternion(),
            offset)

    def write(self):
        action = bpy.data.actions.new(self.name)
        action.use_fake_user = True
        self.armature.animation_data_create()
        # Blender 5.x actions are layered; assigning the action to the armature
        # is what lets fcurve_ensure_for_datablock create the first layer and
        # slot.  Every clip has to be keyed the same way for that to work.
        self.armature.animation_data.action = action
        curves = []
        for bone, frames in self.keys.items():
            for frame, (quaternion, offset) in frames.items():
                pose_bone = self.armature.pose.bones[bone]
                pose_bone.location = offset
                pose_bone.rotation_quaternion = quaternion
                pose_bone.scale = (1.0, 1.0, 1.0)
                # Every component of every path needs its own key.  The
                # previous version walked the paths with `enumerate` and used
                # the same counter as the component index, so only
                # location.x, rotation_quaternion.x and scale.z were ever
                # keyed: a yaw about the bone's own Y axis -- which is where
                # a yaw lands on every bone that points up the spine -- was
                # dropped on the floor, and the character stood there
                # breathing in one axis only.
                for path, components in (("location", 3),
                                         ("rotation_quaternion", 4),
                                         ("scale", 3)):
                    values = getattr(pose_bone, path)
                    for index in range(components):
                        value = values[index]
                        curve = action.fcurve_ensure_for_datablock(
                            self.armature,
                            f'pose.bones["{bone}"].{path}',
                            index=index,
                            group_name=bone)
                        curve.keyframe_points.insert(
                            frame, value, options={"FAST"})
                        curves.append(curve)
                # Every clip returns each bone it touches to rest, so a clip
                # crossfade cannot leave a limb stranded at the last key.
                pose_bone.location = (0.0, 0.0, 0.0)
                pose_bone.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
                pose_bone.scale = (1.0, 1.0, 1.0)
        # Clamped auto handles: a looping breath eases through its keys instead
        # of ticking at each one, and no key can overshoot into the body.
        for curve in curves:
            for keyframe in curve.keyframe_points:
                keyframe.interpolation = "BEZIER"
                keyframe.handle_left_type = "AUTO_CLAMPED"
                keyframe.handle_right_type = "AUTO_CLAMPED"
        self.armature.animation_data.action = None
        action.frame_start = 1
        action.frame_end = self.frames
        self._report(curves)
        return action

    def _report(self, curves):
        """Print what each channel actually recorded.

        A channel can be keyed correctly in Blender and still come out of the
        glTF exporter as a single constant pose -- which reads on screen as a
        character that is wired up but never moves. Comparing the recorded
        value range against the intended one here turns that into a build
        error instead of a runtime mystery.
        """
        report = {}
        seen = set()
        for curve in curves:
            path = curve.data_path
            bone = path.split('"')[1] if '"' in path else path
            channel = path.rsplit('.', 1)[-1] + str(curve.array_index)
            if (bone, channel) in seen:
                continue
            seen.add((bone, channel))
            points = [(keyframe.co[0], keyframe.co[1])
                      for keyframe in curve.keyframe_points]
            report.setdefault(bone, {})[channel] = points

        summary = {}
        for bone, channels in report.items():
            # The four quaternion components have to be read together: a
            # rotation that happens to live entirely in one component looks
            # like a dead channel if each is judged on its own.
            quats = {}
            for index in range(4):
                key = "rotation_quaternion" + str(index)
                if key not in channels:
                    continue
                for frame, value in channels[key]:
                    quats.setdefault(frame, [1.0, 0.0, 0.0, 0.0])[index] = value
            swing = 0.0
            for quat in quats.values():
                length = math.sqrt(sum(c * c for c in quat)) or 1.0
                swing = max(swing, math.degrees(2.0 * math.acos(
                    min(1.0, abs(quat[0]) / length))))

            offsets = {}
            for index in range(3):
                key = "location" + str(index)
                if key not in channels:
                    continue
                for frame, value in channels[key]:
                    offsets.setdefault(frame, [0.0, 0.0, 0.0])[index] = value
            shift = max((math.sqrt(sum(c * c for c in vec))
                         for vec in offsets.values()), default=0.0)
            summary[bone] = {
                "swingDeg": round(swing, 2),
                "shiftUnits": round(shift, 5),
                "keys": len(quats),
            }

        frozen = sorted(
            bone for bone, data in summary.items()
            if bone.startswith(("hips", "spine", "chest", "upperChest", "neck",
                                "head", "halo"))
            and data["swingDeg"] < 0.05
            and data["shiftUnits"] < 1e-5
        )
        print("YXZ_CLIP_STATS " + self.name + " " + json.dumps({
            bone: data
            for bone, data in sorted(summary.items())
            if not bone.startswith(("wing", "leftEye", "rightEye"))
        }))
        if frozen:
            print("YXZ_CLIP_FROZEN " + self.name + " " + ", ".join(frozen))


def idle(arm):
    """Breathing, a slow weight shift and a little wing drift.

    Eight seconds on a two-count breath: the shape of the loop matters more
    than its size, because this clip is what plays whenever nothing else is.

    The amplitudes are deliberately generous. This is a near-white character
    lit from the front, where a one-degree breath is invisible on screen, so
    the loop has to carry a readable weight shift to read as alive at all.
    """
    frames = 8 * FPS
    clip = Clip(arm, "YXZ_Idle", frames)
    for step in range(9):
        frame = 1 + round(frames * step / 8)
        phase = step / 8 * math.tau
        breath = math.sin(phase)
        sway = math.sin(phase - 0.9)
        # The weight shift runs on a longer period than the breath so the two
        # never line up into a single pulse.
        shift = math.sin(phase * 0.5 - 0.6)
        clip.pose(frame, "hips", lift=0.014 * breath, yaw=2.6 * shift,
                  roll=1.4 * shift)
        clip.pose(frame, "spine", pitch=-2.6 * breath, roll=1.9 * sway,
                  yaw=-1.5 * shift)
        clip.pose(frame, "chest", pitch=-3.2 * breath, roll=-2.4 * sway,
                  yaw=-1.8 * shift)
        clip.pose(frame, "upperChest", pitch=-2.1 * breath, yaw=3.4 * sway,
                  roll=-1.2 * shift)
        clip.pose(frame, "neck", roll=2.8 * sway, pitch=-1.9 * breath,
                  yaw=-1.4 * shift)
        clip.pose(frame, "head", roll=4.6 * sway, pitch=-3.2 * breath,
                  yaw=2.6 * shift + 1.4 * sway)
        clip.pose(frame, "leftUpperArm", roll=-4.6 * sway, yaw=2.0 * breath)
        clip.pose(frame, "leftLowerArm", roll=-3.2 * breath, yaw=1.6 * sway)
        clip.pose(frame, "rightUpperArm", roll=4.2 * sway, yaw=-2.0 * breath)
        clip.pose(frame, "rightLowerArm", roll=2.6 * breath, yaw=-1.4 * sway)
        clip.pose(frame, "leftUpperLeg", pitch=1.4 * shift)
        clip.pose(frame, "leftLowerLeg", pitch=-1.8 * shift)
        clip.pose(frame, "rightUpperLeg", pitch=-1.4 * shift)
        clip.pose(frame, "rightLowerLeg", pitch=1.8 * shift)
        clip.pose(frame, "wing.L", yaw=6.5 * breath, pitch=2.4 * sway)
        clip.pose(frame, "wing.R", yaw=-6.5 * breath, pitch=-2.4 * sway)
        clip.pose(frame, "halo", yaw=4.5 * breath, roll=2.0 * sway)
    return clip


def listening(arm):
    """Leaning in, with the small nods that read as 'I am following you'."""
    frames = 6 * FPS
    clip = Clip(arm, "YXZ_Listening", frames)
    # Two nods across the loop, so the head is never completely still.
    nods = [(0.00, 0.0), (0.18, 3.4), (0.34, 0.4), (0.52, 2.6),
            (0.68, 0.2), (1.00, 0.0)]
    for step in range(9):
        frame = 1 + round(frames * step / 8)
        t = step / 8
        nod = _smooth_cycle(nods, t)
        drift = math.sin(t * math.tau)
        clip.pose(frame, "hips", lift=0.008 * drift, yaw=1.6 * drift)
        clip.pose(frame, "spine", pitch=-1.8 * drift, yaw=-1.2 * drift)
        clip.pose(frame, "chest", pitch=-2.4 * nod, roll=-1.6 * drift)
        clip.pose(frame, "upperChest", pitch=4.0 + 1.4 * drift,
                  yaw=2.8 * drift)
        clip.pose(frame, "neck", roll=4.6 * drift, pitch=2.0 * nod)
        clip.pose(frame, "head", roll=7.0 * drift, pitch=4.0 + 5.5 * nod,
                  yaw=5.0 + 2.6 * drift)
        clip.pose(frame, "leftUpperArm", roll=-7.0 - 2.5 * drift, yaw=3.0)
        clip.pose(frame, "leftLowerArm", roll=-4.0 * drift)
        clip.pose(frame, "rightUpperArm", roll=5.0 + 2.0 * drift)
        clip.pose(frame, "wing.L", yaw=8.0 + 3.5 * drift, pitch=2.0 * nod)
        clip.pose(frame, "wing.R", yaw=-6.5 - 2.5 * drift, pitch=-2.0 * nod)
    return clip


def thinking(arm):
    """Head cocked to one side, drifting, with the hand loose at the chin."""
    frames = 8 * FPS
    clip = Clip(arm, "YXZ_Thinking", frames)
    for step in range(9):
        frame = 1 + round(frames * step / 8)
        t = step / 8
        drift = math.sin(t * math.tau)
        slow = math.sin(t * math.tau * 0.5)
        # A separate, faster beat so the hand and head keep tapping while the
        # torso holds its thinking lean. Without it the clip is a static pose
        # that reads on screen as "no animation at all".
        tap = math.sin(t * math.tau * 4.0)
        clip.pose(frame, "hips", lift=0.006 * drift, yaw=-2.2 * drift)
        clip.pose(frame, "spine", roll=3.4 * slow, yaw=-2.8 * drift,
                  pitch=-1.6 * slow)
        clip.pose(frame, "chest", roll=4.4 * slow, yaw=-4.0 * drift,
                  pitch=-1.2 * tap)
        clip.pose(frame, "upperChest", roll=5.2 * slow, yaw=-4.8 * drift,
                  pitch=2.8 + 1.4 * tap)
        clip.pose(frame, "neck", roll=5.6 * slow, yaw=-4.0 * drift,
                  pitch=2.0 * tap)
        clip.pose(frame, "head", roll=9.5 * slow, yaw=-7.0 - 3.0 * drift,
                  pitch=5.5 + 2.6 * tap)
        # The right arm is the low one on this asset, so lifting it reads as a
        # hand drifting up to the chin rather than as a wave.
        clip.pose(frame, "rightShoulder", pitch=-4.5 + 0.8 * tap)
        clip.pose(frame, "rightUpperArm", roll=34.0 + 4.0 * drift,
                  pitch=-8.0, yaw=-6.0 + 1.5 * tap)
        clip.pose(frame, "rightLowerArm", roll=-42.0 - 5.0 * drift,
                  yaw=-8.0 + 2.0 * tap)
        clip.pose(frame, "rightHand", roll=18.0 + 9.0 * tap)
        clip.pose(frame, "leftUpperArm", roll=-3.0 * drift, yaw=1.5 * tap)
        clip.pose(frame, "leftLowerArm", roll=-2.0 * drift)
        clip.pose(frame, "wing.L", yaw=4.0 + 3.0 * drift)
        clip.pose(frame, "wing.R", yaw=-9.0 - 4.0 * drift, pitch=-2.0 * slow)
        clip.pose(frame, "halo", yaw=-5.0 * slow, roll=3.0 * drift)
    return clip


def speaking(arm):
    """A two-beat body pulse per phrase, plus a small explanatory gesture.

    The clip is deliberately short: it loops under the speech envelope, so a
    long clip would visibly restart mid-sentence.
    """
    frames = 4 * FPS
    clip = Clip(arm, "YXZ_Speaking", frames)
    for step in range(9):
        frame = 1 + round(frames * step / 8)
        t = step / 8
        pulse = math.sin(t * math.tau * 2.0)
        accent = math.sin(t * math.tau - 1.2)
        clip.pose(frame, "hips", lift=0.0045 * pulse, yaw=1.0 * accent)
        clip.pose(frame, "spine", pitch=-1.6 * pulse, roll=1.2 * accent)
        clip.pose(frame, "chest", pitch=-2.0 * pulse, yaw=1.8 * accent)
        clip.pose(frame, "upperChest", pitch=-1.4 * pulse, yaw=2.2 * accent)
        clip.pose(frame, "neck", pitch=-1.6 * pulse, roll=1.8 * accent)
        clip.pose(frame, "head", pitch=-2.6 * pulse, yaw=3.4 * accent,
                  roll=2.2 * accent)
        clip.pose(frame, "leftUpperArm", roll=-8.0 - 3.0 * accent,
                  yaw=6.0 * accent)
        clip.pose(frame, "leftLowerArm", roll=-8.0 - 6.0 * accent)
        clip.pose(frame, "leftHand", roll=-10.0 * accent, yaw=8.0 * accent)
        clip.pose(frame, "rightUpperArm", roll=4.0 + 2.0 * pulse)
        clip.pose(frame, "wing.L", yaw=6.0 + 3.0 * pulse)
        clip.pose(frame, "wing.R", yaw=-5.0 - 3.0 * pulse)
    return clip


def success(arm):
    """A one-shot cheer: both arms up, one hop, wings open, settle.

    This one plays as `LoopOnce`, so the first and last keys are not a loop
    point -- the tail has to come back to rest on its own.

    The book is welded to the right hand, so that arm cannot swing out like
    a free arm: at 48 degrees the book stuck out sideways and read as a
    second wing.  It stays close to the body here and the cheer is carried
    by the free arm, the hop and the wing flare instead.
    """
    frames = 5 * FPS
    clip = Clip(arm, "YXZ_Success", frames)
    poses = [
        (0.00, 0.0),
        (0.14, 1.0),
        (0.26, 0.35),
        (0.38, 0.95),
        (0.52, 0.30),
        (0.70, 0.55),
        (1.00, 0.0),
    ]
    for step in range(11):
        frame = 1 + round(frames * step / 10)
        t = step / 10
        cheer = _smooth_cycle(poses, t)
        lift = 0.040 * cheer
        clip.pose(frame, "hips", lift=lift, pitch=-2.0 * cheer)
        clip.pose(frame, "spine", pitch=-3.0 * cheer)
        clip.pose(frame, "chest", pitch=-3.4 * cheer, yaw=2.0 * cheer)
        clip.pose(frame, "upperChest", pitch=-2.4 * cheer, yaw=3.0 * cheer)
        clip.pose(frame, "neck", pitch=-3.0 * cheer)
        clip.pose(frame, "head", pitch=-4.5 * cheer, yaw=2.0 * cheer)
        clip.pose(frame, "leftShoulder", pitch=-7.0 * cheer)
        clip.pose(frame, "leftUpperArm", roll=-9.0 * cheer,
                  yaw=8.0 * cheer, pitch=-4.0 * cheer)
        clip.pose(frame, "leftLowerArm", roll=-12.0 * cheer,
                  yaw=12.0 * cheer * math.sin(t * math.tau * 3.0))
        clip.pose(frame, "rightUpperArm", roll=10.0 * cheer,
                  yaw=-7.0 * cheer, pitch=-4.0 * cheer)
        clip.pose(frame, "rightLowerArm", roll=12.0 * cheer)
        clip.pose(frame, "wing.L", yaw=30.0 * cheer, pitch=8.0 * cheer)
        clip.pose(frame, "wing.R", yaw=-30.0 * cheer, pitch=-8.0 * cheer)
        clip.pose(frame, "halo", yaw=26.0 * cheer)
    return clip


def wave(arm):
    """The greeting wave: arm up, forearm swinging, torso keeping time."""
    frames = 4 * FPS
    clip = Clip(arm, "YXZ_Wave", frames)
    for step in range(13):
        frame = 1 + round(frames * step / 12)
        t = step / 12
        phase = t * math.tau * 2.0
        clip.pose(frame, "hips", lift=0.004 * math.sin(phase))
        clip.pose(frame, "spine", yaw=-1.5 * math.sin(phase))
        clip.pose(frame, "chest", yaw=-2.0 * math.sin(phase))
        clip.pose(frame, "upperChest", yaw=-2.4 * math.sin(phase))
        clip.pose(frame, "neck", roll=-1.6 * math.sin(phase))
        clip.pose(frame, "head", roll=-3.0 * math.sin(phase),
                  yaw=-2.0 * math.sin(phase))
        clip.pose(frame, "leftShoulder", pitch=-3.0)
        clip.pose(frame, "leftUpperArm", roll=-5.0, pitch=-3.0,
                  yaw=-2.0)
        _wave(clip, frame, phase, 1.0)
        clip.pose(frame, "wing.L", yaw=16.0 + 4.0 * math.sin(phase))
        clip.pose(frame, "wing.R", yaw=-14.0 - 4.0 * math.sin(phase))
        clip.pose(frame, "halo", yaw=9.0 * math.sin(phase))
    return clip


def _wave(clip, frame, phase, amplitude=1.0):
    """Swing the raised forearm and hand without moving the torso root.

    The greeting pose is authored on the left arm (the arm raised in the
    reference). Keeping the oscillation on the lower arm and hand gives a
    readable wave while avoiding the whole-body twist that previously made
    the Tripo envelope skin look rubbery.
    """
    swing = math.sin(phase) * amplitude
    clip.pose(frame, "leftLowerArm", roll=9.0 * swing,
              yaw=20.0 * swing)
    clip.pose(frame, "leftHand", roll=-22.0 * swing,
              yaw=8.0 * swing)


def _smooth_cycle(points, t):
    """Sample a list of (time, value) knots with a smoothstep between them."""
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t <= t1:
            span = t1 - t0
            blend = 0.0 if span <= 0.0 else (t - t0) / span
            blend = blend * blend * (3.0 - 2.0 * blend)
            return v0 + (v1 - v0) * blend
    return points[-1][1]


CLIPS = (idle, listening, thinking, speaking, success, wave)


def add_clips(arm):
    """Author every clip and leave the rig back at rest."""
    bpy.context.scene.render.fps = FPS
    names = []
    for factory in CLIPS:
        clip = factory(arm)
        clip.write()
        names.append(clip.name)
    for pose_bone in arm.pose.bones:
        pose_bone.matrix_basis = Matrix.Identity(4)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
        pose_bone.scale = (1.0, 1.0, 1.0)
    print("YXZ_CLIPS " + str(names))
    return names
