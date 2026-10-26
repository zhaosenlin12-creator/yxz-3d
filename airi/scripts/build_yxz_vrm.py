"""Rebuild the YXZ character as a real VRM humanoid instead of envelope skin.

The previous rig placed the arm bones along X while the character's left/right
axis is Y, so every arm rotation swung the limb forward instead of sideways and
the automatic envelope weights could not bind to geometry outside the mesh.
This script derives the skeleton from measured mesh landmarks, skins it with
deterministic distance-to-segment weights, and writes a GLB that
`vrm_postprocess.py` then turns into a VRM 1.0 asset.

Two things about this asset drive the whole design.  It is a *pose*, not a
neutral character: one arm is raised in a wave and the other hangs down
holding a book, so the skeleton has to be read off the mesh rather than
assumed.  And it arrives as 229 disconnected blobs, so a region gate applied
to the whole mesh cannot tell the raised hand from the cheek it is pressed
against -- a gate that says "above the shoulders, therefore the head"
swallows the whole arm and a wave tears the hand off the face.

  blender -b -P scripts/build_yxz_vrm.py -- \
    --source <glb> --output <glb> [--blend <blend>] [--no-face]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


# Used when a visor ray misses; keeps the eye bones off the body midline.
FALLBACK_FACE_Y = -0.238


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


# The Tripo asset is authored Z-up with the character facing +X. glTF is Y-up
# and three-vrm hardcodes lookAt.faceFront to (0, 0, 1), so the exported asset
# must face +Z. Blender's exporter maps (x, y, z) -> (x, z, -y), which means
# facing -Y in Blender is what ends up facing +Z in glTF.
def R(point):
    """Measured frame -> exported frame, a -90 degree turn around Z."""
    return (point[1], -point[0], point[2])


# --- measured landmarks, in the original Tripo frame -------------------------

LEG_Y = 0.095
LEG_X = 0.040
HIPS_Z = -0.190
KNEE_Z = -0.335
ANKLE_Z = -0.425
BALL_X = 0.115
TOE_X = 0.160

SPINE_Z = -0.130
CHEST_Z = -0.060
UPPER_CHEST_Z = -0.015
NECK_BASE_Z = -0.040
NECK_TOP_Z = 0.000
# The helmet is a 0.48-unit oblate sphere spanning z -0.09..0.39, so a short
# head bone left the lower skull blending into the neck and the skull cracked
# whenever the head turned.  The bone has to span the helmet it drives.
HEAD_BASE_Z = 0.000
HEAD_TOP_Z = 0.360

# The raised arm is the character's left (+Y); the arm carrying the book is
# the right (-Y).  Every joint below is measured off the mesh: slicing each
# limb across its own axis gives its medial line, and the finger blobs turn
# out to be a flat plate that runs from the knuckle out to the fingertips.
#
# The hand bone has to reach that plate.  Stop it at the wrist and the
# fingertips sit further from the hand bone than from the forearm, so a
# wave drags them into spikes -- which is exactly what the old rig did.
ARM_R = {"shoulder": (0.049, 0.116, -0.052),
         "elbow": (0.095, 0.180, -0.075),
         "wrist": (0.180, 0.310, 0.005),
         "hand": (0.192, 0.215, 0.015)}
ARM_L = {"shoulder": (-0.045, -0.130, -0.050),
         "elbow": (0.070, -0.150, -0.130),
         "wrist": (0.098, -0.195, -0.195),
         "hand": (0.132, -0.207, -0.295)}

# The middle of the skull cavity, in the exported frame.  The helmet is a
# closed shell around this point, and a ray leaving it always meets the
# visor before it meets the raised hand.
HEAD_CENTRE_EXPORTED = (0.0, 0.02, 0.17)


def spine_chain():
    return [
        ("hips", (LEG_X, 0.0, HIPS_Z), (LEG_X, 0.0, SPINE_Z), None),
        ("spine", (LEG_X, 0.0, SPINE_Z), (LEG_X, 0.0, CHEST_Z), "hips"),
        ("chest", (LEG_X, 0.0, CHEST_Z), (LEG_X, 0.0, UPPER_CHEST_Z), "spine"),
        ("upperChest", (LEG_X, 0.0, UPPER_CHEST_Z), (LEG_X, 0.0, NECK_BASE_Z), "chest"),
        ("neck", (LEG_X, 0.0, NECK_BASE_Z), (LEG_X, 0.0, NECK_TOP_Z), "upperChest"),
        ("head", (LEG_X, 0.0, HEAD_BASE_Z), (LEG_X, 0.0, HEAD_TOP_Z), "neck"),
    ]


def arm_chain(side, sign, arm):
    """side is 'left'/'right' in VRM terms; sign is the measured Y direction."""
    shoulder = arm["shoulder"]
    return [
        (side + "Shoulder", (0.030, sign * 0.045, -0.010), shoulder, "upperChest"),
        (side + "UpperArm", shoulder, arm["elbow"], side + "Shoulder"),
        (side + "LowerArm", arm["elbow"], arm["wrist"], side + "UpperArm"),
        (side + "Hand", arm["wrist"], arm["hand"], side + "LowerArm"),
    ]


def leg_chain(side, sign):
    hip = (LEG_X, sign * LEG_Y, HIPS_Z)
    knee = (LEG_X, sign * LEG_Y, KNEE_Z)
    ankle = (LEG_X, sign * LEG_Y, ANKLE_Z)
    ball = (BALL_X, sign * LEG_Y, -0.475)
    return [
        (side + "UpperLeg", hip, knee, "hips"),
        (side + "LowerLeg", knee, ankle, side + "UpperLeg"),
        (side + "Foot", ankle, ball, side + "LowerLeg"),
        (side + "Toes", ball, (TOE_X, sign * LEG_Y, -0.478), side + "Foot"),
    ]


def eye_bones(eye_x, eye_y, eye_z):
    """Eye bones pivot just behind the visor panel.

    The iris caps ride on these, so the pivot has to sit on the panel rather
    than back at the head centre: a pivot 0.24 behind the face would swing the
    iris clean off the sclera at the first glance sideways.

    These coordinates are already in the exported frame.  Every other bone is
    measured on the Tripo asset and rotated by R() below, and running the eye
    bones through R as well put the pivot a third of a unit off to the side.
    """
    out = []
    for side, sign in (("left", 1.0), ("right", -1.0)):
        out.append((side + "Eye", (sign * eye_x, eye_y, eye_z),
                    (sign * (eye_x - 0.05), eye_y, eye_z), "head", True))
    return out


def bone_table(eye_pivot):
    # In the measured frame the character faces +X with up +Z, so its own left
    # is +Y: that is the side carrying the raised waving arm.  VRM side names
    # must follow the character's left/right, not the render's screen side.
    table = [(n, h, t, p, False) for n, h, t, p in spine_chain()]
    table += [(n, h, t, p, False) for n, h, t, p in
              arm_chain("left", 1.0, ARM_R) + leg_chain("left", 1.0)]
    table += [(n, h, t, p, False) for n, h, t, p in
              arm_chain("right", -1.0, ARM_L) + leg_chain("right", -1.0)]
    table += eye_bones(*eye_pivot)
    return table


# The halo floats behind and above the helmet, so it hangs off the chest rather
# than the head; otherwise every head turn swings it across the sky.
# The wings get a bone each, running from where they meet the body out to
# their tip, so they can drift instead of being welded to the back.
HELPER_BONES = [
    ("halo", (-0.20, 0.0, 0.410), (-0.16, 0.0, 0.480), "upperChest"),
    ("wing.L", (-0.095, 0.160, -0.145), (-0.165, 0.360, -0.150), "upperChest"),
    ("wing.R", (-0.095, -0.160, -0.145), (-0.165, -0.360, -0.150), "upperChest"),
]


def build_armature(eye_pivot):
    arm_data = bpy.data.armatures.new("YXZ_Armature")
    arm = bpy.data.objects.new("YXZ_Armature", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    created = {}
    for name, head, tail, parent, exported in bone_table(eye_pivot):
        bone = arm_data.edit_bones.new(name)
        bone.head = head if exported else R(head)
        bone.tail = tail if exported else R(tail)
        if parent:
            bone.parent = created[parent]
            bone.use_connect = False
        created[name] = bone

    # Helper bones that are not part of the VRM humanoid: the floating halo and
    # the feather plates, so each can move without dragging the torso with it.
    for name, head, tail, parent in HELPER_BONES:
        bone = arm_data.edit_bones.new(name)
        bone.head = R(head)
        bone.tail = R(tail)
        bone.parent = created[parent]
        bone.use_connect = False
        created[name] = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    for pose_bone in arm.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    return arm, created


def segment_distance(points, head, tail):
    """Distance from every point to one bone segment."""
    segment = tail - head
    length_sq = float(segment @ segment)
    if length_sq < 1e-12:
        return np.linalg.norm(points - head, axis=1)
    t = np.clip(((points - head) @ segment) / length_sq, 0.0, 1.0)
    closest = head + t[:, None] * segment
    return np.linalg.norm(points - closest, axis=1)


class _Union:
    """Union-find over vertex indices."""

    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def mesh_parts(mesh_obj):
    """The connected components of the mesh, largest first.

    The Tripo export arrives as 229 disconnected blobs.  Splitting it first
    is what makes the rest of the skinning possible: a rule decided per
    blob can tell the raised hand from the visor it is pressed against,
    because the visor is a different blob even though the two overlap in
    space.
    """
    count = len(mesh_obj.data.vertices)
    groups = _Union(count)
    for edge in mesh_obj.data.edges:
        groups.union(edge.vertices[0], edge.vertices[1])
    labels = np.array([groups.find(i) for i in range(count)], dtype=np.int64)
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    boundaries = np.flatnonzero(np.diff(sorted_labels)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [count]))
    parts = [order[start:end] for start, end in zip(starts, ends)]
    parts.sort(key=lambda block: -len(block))
    return parts


def head_shell_blobs(mesh_obj, parts, owner, centre, samples=320):
    """The blobs a ray leaving the middle of the skull reaches first.

    The helmet is a closed shell, so every direction out of the middle of
    the head leaves through it, and the shell is the only thing a ray from
    inside the skull can find first.  That is the one test that separates
    the helmet from the raised hand: the hand is pressed against the cheek
    at the same height, so no coordinate test tells the two apart, but a
    ray from the middle of the head always meets the visor before the hand.

    Downward rays are skipped, because they leave through the collar and
    would tag the chest as part of the head.
    """
    mesh_obj.data.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in mesh_obj.data.loop_triangles]
    bvh = BVHTree.FromPolygons(
        [v.co[:] for v in mesh_obj.data.vertices], triangles, all_triangles=True)

    hits = np.zeros(len(parts), dtype=np.int32)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for sample in range(samples):
        height = 1.0 - 2.0 * (sample + 0.5) / samples
        radius = math.sqrt(max(0.0, 1.0 - height * height))
        theta = golden * sample
        direction = Vector((math.cos(theta) * radius, math.sin(theta) * radius,
                            height))
        if direction.z < -0.35:
            continue
        found = bvh.ray_cast(Vector(centre), direction)
        if found[0] is None:
            continue
        hits[owner[triangles[found[2]][0]]] += 1
    return [index for index, count in enumerate(hits) if count >= 4]


def chain_parameter(points, chain):
    """Where every point lands along a joint chain, and how far off it is.

    `u` counts segments: 0 at the first joint, 1 at the second, and so on.
    It is what tells a fingertip (u ~ 2.9, past the wrist) apart from a
    forearm (u ~ 1.5) even though the two are the same distance from the
    wrist.
    """
    best_u = np.zeros(len(points), dtype=np.float32)
    best_d = np.full(len(points), np.inf, dtype=np.float32)
    for index in range(len(chain) - 1):
        head = chain[index]
        tail = chain[index + 1]
        segment = tail - head
        length_sq = float(segment @ segment)
        if length_sq < 1e-12:
            continue
        t = np.clip(((points - head) @ segment) / length_sq, 0.0, 1.0)
        closest = head + t[:, None] * segment
        distance = np.linalg.norm(points - closest, axis=1)
        closer = distance < best_d
        best_d = np.where(closer, distance, best_d)
        best_u = np.where(closer, index + t, best_u)
    return best_u, best_d


def joint_chain(arm, side):
    """The joint positions of one arm, in the order a hand travels them."""
    upper = arm.data.bones[side + "UpperArm"]
    lower = arm.data.bones[side + "LowerArm"]
    hand = arm.data.bones[side + "Hand"]
    return [np.array(bone.head_local, dtype=np.float32)
            for bone in (upper, lower, hand)] + [
        np.array(hand.tail_local, dtype=np.float32)]


def eye_pivot(mesh_obj):
    """Where the eye bones have to sit for the iris caps to rotate in place."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_yxz_face import EYE_X, EYE_Z

    mesh_obj.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons(
        [v.co[:] for v in mesh_obj.data.vertices],
        [tuple(t.vertices) for t in mesh_obj.data.loop_triangles],
        all_triangles=True,
    )
    # The iris stack floats IRIS_RIM_LIFT in front of the sclera, so the pivot
    # goes the same distance behind the panel; the character faces -Y here.
    depth = 0.014
    hits = []
    for sign in (1.0, -1.0):
        found = bvh.ray_cast(Vector((sign * EYE_X, -3.0, EYE_Z)),
                             Vector((0.0, 1.0, 0.0)))
        hits.append(FALLBACK_FACE_Y if found[0] is None else found[0].y)
    return (EYE_X, sum(hits) / len(hits) + depth, EYE_Z)


def quantise(weights, steps=64):
    """Round to 1/steps while keeping every row summing to exactly 1."""
    scaled = weights * steps
    units = np.floor(scaled).astype(np.int32)
    residual = np.round(scaled - units).astype(np.int32)
    for _ in range(3):
        deficit = steps - units.sum(axis=1)
        if deficit.max() <= 0:
            break
        order = np.argsort(-residual, axis=1)
        ranked = np.take_along_axis(units, order, axis=1)
        ranked_residual = np.take_along_axis(residual, order, axis=1)
        take = (ranked_residual > 0) & (deficit > 0)[:, None]
        np.put_along_axis(units, order, ranked + take, axis=1)
        np.put_along_axis(residual, order, np.where(take, 0, ranked_residual), axis=1)
    return units


def skin_mesh(mesh_obj, arm, bone_names, weight_path):
    """Distance-to-segment skinning, then bulk-write the quantised weights.

    The distance weighting spreads the blend across each joint instead of
    stepping it, but it cannot be trusted to decide *which* bone owns a
    region: the visor and the raised hand occupy the same volume, and the
    hand is closer to the head bone than to the hand bone unless the hand
    bone is long enough to reach the fingertips.  So the blobs are sorted
    out first and the ambiguous ones are pinned.
    """
    count = len(mesh_obj.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh_obj.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)

    # The eye bones sit inside the helmet, so distance weighting would hand them
    # a large slice of the skull and rotating them for look-at would tear the
    # head apart.  They stay out of the skin entirely; the eyeball meshes are
    # parented to them directly instead.
    usable = [n for n in bone_names
              if n in arm.data.bones and not n.endswith(("leftEye", "rightEye"))]
    distances = np.empty((count, len(usable)), dtype=np.float32)
    for index, name in enumerate(usable):
        bone = arm.data.bones[name]
        head = np.array(bone.head_local, dtype=np.float32)
        tail = np.array(bone.tail_local, dtype=np.float32)
        distances[:, index] = segment_distance(coords, head, tail)

    weights = 1.0 / (distances ** 3 + 1e-6)
    # Keeping only the top few bones made the shoulder transition a hard step:
    # a pauldron vertex would jump from 100% shoulder to 50/50 upper arm within
    # a couple of centimetres, and any real arm rotation sheared the mesh
    # there.  A relative cutoff spreads the blend across the joint instead.
    weights[weights < weights.max(axis=1, keepdims=True) * 0.06] = 0.0
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-8)

    x, y, z = coords[:, 0], coords[:, 1], coords[:, 2]

    parts = mesh_parts(mesh_obj)
    owner = np.empty(count, dtype=np.int32)
    for index, block in enumerate(parts):
        owner[block] = index

    def pin(mask, bone_name):
        if not mask.any():
            return
        weights[mask, :] = 0.0
        weights[mask, usable.index(bone_name)] = 1.0

    # The helmet top ends at z 0.3875 and the halo starts at z 0.4038, so
    # this threshold separates them without touching either shape.  The
    # helmet's own crown reaches up into the same band, so the head is
    # pinned after the halo and wins: otherwise the crown is handed to
    # the halo and torn away from the rest of the skull.
    halo = z > 0.393
    pin(halo, "halo")

    # The helmet: the blobs a ray out of the middle of the skull reaches
    # first.  Only those are welded to the head bone, which is what keeps
    # the raised arm out of the skull.
    head_blobs = head_shell_blobs(mesh_obj, parts, owner,
                                   HEAD_CENTRE_EXPORTED)
    head = np.zeros(count, dtype=bool)
    for blob in head_blobs:
        head |= owner == blob
    pin(head & ~halo, "head")

    # The feather plates sit at the back where the arms also live; pinning them
    # to upperChest stops a wave from tearing the wings off the body.  They
    # get a bone of their own so they can drift, and the plate blends into
    # the chest towards its root so the flap does not open a gap there.
    wing_region = (y > 0.04) & (np.abs(x) > 0.16) & (z > -0.28) & (z < -0.05)
    for blob in range(len(parts)):
        block = owner == blob
        if not block.any() or wing_region[block].mean() < 0.6:
            continue
        side = "wing.L" if x[block].mean() > 0 else "wing.R"
        bone = arm.data.bones[side]
        head_point = np.array(bone.head_local, dtype=np.float32)
        tail_point = np.array(bone.tail_local, dtype=np.float32)
        direction = tail_point - head_point
        along = np.clip(((coords[block] - head_point) @ direction)
                        / float(direction @ direction), 0.0, 1.0)
        ramp = along ** 2
        weights[block, :] = 0.0
        weights[block, usable.index("upperChest")] = 1.0 - ramp
        weights[block, usable.index(side)] = ramp

    # The fingers are their own blobs, and they are the reason a wave used
    # to end in spikes: the hand bone stopped at the wrist, so a fingertip
    # was closer to the forearm than to the hand and followed the forearm
    # instead.  Blobs that sit past the wrist along the arm's own chain are
    # the hand, and the hand bone now reaches the fingertips.  The book
    # hangs off the same hand, and it has to be rigid: left to distance
    # weighting its near edge follows the hand while its far edge follows
    # the forearm, which folds it in half.
    for side in ("left", "right"):
        chain = joint_chain(arm, side)
        u, _ = chain_parameter(coords, chain)
        for blob in range(len(parts)):
            block = owner == blob
            if not block.any() or len(block) > 900:
                continue
            if np.median(u[block]) < 2.3:
                continue
            pin(block, side + "Hand")

    # The lower bound matters as much as the others.  Every book and
    # right-finger blob sits at z >= -0.33, but the character's right boot
    # also falls inside x < -0.14 / z < -0.16 / y in (-0.20, 0) -- and at
    # z = -0.47 it projects past the wrist just as convincingly as a
    # fingertip does, so it satisfied the chain test too.  It got welded to
    # the right hand and rode every gesture out into the air beside the
    # character as a floating shard.
    book = (x < -0.14) & (z < -0.16) & (z > -0.40) & (y > -0.20) & (y < 0.0)
    right_u, _ = chain_parameter(coords, joint_chain(arm, "right"))
    claimed = [blob for blob in range(len(parts))
               if (owner == blob).any()
               and book[owner == blob].mean() >= 0.6]
    claimed_z = [float(z[owner == blob].mean()) for blob in claimed]
    print("YXZ_BOOK_CLAIM blobs=" + str(len(claimed))
          + " zMin=" + (str(round(min(claimed_z), 3)) if claimed_z else "none")
          + " zMax=" + (str(round(max(claimed_z), 3)) if claimed_z else "none"))
    for blob in range(len(parts)):
        block = owner == blob
        if not block.any() or book[block].mean() < 0.6:
            continue
        if np.median(right_u[block]) < 2.2:
            continue
        pin(block, "rightHand")

    units = quantise(weights)
    # Rest-space audit of every blob against the bone that ended up owning it.
    # A Tripo part bound to a bone it does not touch does not tear -- it
    # travels with that limb and hangs in the air beside the character, which
    # is invisible in a still of the rest pose and obvious in a clip.  The
    # book mask caught a boot this way once; this reports any others.
    # Only small blobs bound to a limb bone.  A big shell (helmet, visor) is
    # pinned rigidly and its centroid simply sits away from the bone; the
    # wing plates are meant to sit on upperChest out at the root.  What
    # actually goes wrong is a finger- or toe-sized part welded to a hand or
    # foot on the far side of the body.
    limb = {"Shoulder", "UpperArm", "LowerArm", "Hand",
            "UpperLeg", "LowerLeg", "Foot", "Toes"}
    loose = []
    for blob in range(len(parts)):
        block = owner == blob
        if not block.any() or block.sum() > 900:
            continue
        column = weights[block].mean(axis=0)
        name = usable[int(np.argmax(column))]
        if column.max() < 0.5 or not any(name.endswith(b) for b in limb):
            continue
        bone = arm.data.bones[name]
        head = np.array(bone.head_local, dtype=np.float32)
        tail = np.array(bone.tail_local, dtype=np.float32)
        axis = tail - head
        span = float(axis @ axis)
        t = 0.0 if span < 1e-12 else float(
            np.clip(((coords[block].mean(axis=0) - head) @ axis) / span, 0.0, 1.0))
        gap = float(np.linalg.norm(coords[block].mean(axis=0) - (head + t * axis)))
        if gap > 0.12:
            loose.append([blob, int(block.sum()), name, round(gap, 3)])
    loose.sort(key=lambda row: -row[3])
    print("YXZ_LOOSE_BLOBS " + json.dumps(loose[:12]))
    stats = {}
    for index, name in enumerate(usable):
        column = units[:, index]
        group = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)
        total = 0
        for level in range(1, units.max() + 1):
            picked = np.flatnonzero(column == level)
            if picked.size == 0:
                continue
            group.add(picked.tolist(), level / 64.0, "ADD")
            total += int(picked.size)
        stats[name] = total

    modifier = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = arm
    modifier.use_vertex_groups = True
    mesh_obj.parent = arm

    weight_path.write_text(
        json.dumps({"vertices": count, "influences": stats}, indent=2), encoding="utf-8")
    return stats


def lookat_offset(arm, eye):
    """The eye centre expressed in head-bone local space, in glTF axes.

    three-vrm treats `offsetFromHeadBone` as a *position*: it runs
    `offset.applyMatrix4(head.matrixWorld)` to get the point the gaze
    rotates around.  A unit-length forward vector therefore parks that pivot
    a metre in front of the skull, which shrinks every measured yaw/pitch by
    roughly the eye distance and reads as a dead, unfocused stare.

    The offset is expressed in the *head node's* local frame, and that frame
    is not the armature frame: a bone's local +Y runs along the bone, so the
    head bone's frame is turned 90 degrees around X relative to the rig.
    Running the axis swap on the bone-local vector therefore swaps the
    up axis for the forward axis and lands the gaze pivot *behind* the
    skull, which is what a dead, unfocused stare looks like.

    The offset has to be measured in the armature frame first -- the eye
    centre minus the head bone's rest origin -- and only then run through
    the same Blender->glTF axis swap the exporter applies.
    """
    head = arm.data.bones["head"]
    centre = Vector((0.0, eye[1], eye[2]))
    offset = centre - head.matrix_local.translation
    return [round(offset.x, 6), round(offset.z, 6), round(-offset.y, 6)]


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    blend = value_after("--blend")
    add_face = "--no-face" not in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    mesh_obj = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )

    # Rotate mesh data into the exported frame so object transforms stay
    # identity; every bone coordinate below is authored in that same frame.
    mesh_obj.data.transform(Matrix.Rotation(math.radians(-90.0), 4, "Z"))
    mesh_obj.data.update()

    eye = eye_pivot(mesh_obj)
    arm, edit_bones = build_armature(eye)
    weight_path = output.with_suffix(".weights.json")
    stats = skin_mesh(mesh_obj, arm, list(edit_bones.keys()), weight_path)
    offset = lookat_offset(arm, eye)
    output.with_suffix(".lookat.json").write_text(
        json.dumps({"offsetFromHeadBone": offset}), encoding="utf-8")

    if add_face:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from build_yxz_face import attach_face

        print("YXZ_FACE_REPORT " + json.dumps(attach_face(mesh_obj, arm)))

    # The halo is an object of its own rather than a part of the body, so
    # that it can carry a light.  A ring that shares the body's material
    # shares the body's lighting, and a lit band of plastic above a
    # character's head is a hoop, not a halo.
    if "--no-halo" not in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from build_yxz_halo import attach_halo

        print("YXZ_HALO_REPORT " + json.dumps(attach_halo(arm)))

    if "--no-clips" not in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from build_yxz_clips import add_clips

        add_clips(arm)

    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_apply=False,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_skins=True,
        export_morph=True,
        export_yup=True,
        export_draco_mesh_compression_enable=False,
    )
    # Blender writes mesh.weights as all ones, which would make three-vrm
    # start with every viseme and every blink fully applied.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from glb_json import neutralise_weights, read_glb, write_glb

    document, binary = read_glb(output)
    print("YXZ_NEUTRALISED " + str(neutralise_weights(document)))
    write_glb(output, document, binary)
    print("YXZ_BUILD_STATS " + json.dumps(stats))
    print("YXZ_BUILT " + str(output))


if __name__ == "__main__":
    main()
