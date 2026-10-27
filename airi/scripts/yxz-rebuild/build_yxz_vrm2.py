"""Rebuild the YXZ avatar as a VRM from the reconstructed body mesh.

The asset the front-end loads -- `yxz.vrm` -- was never committed:
`.gitignore` excludes `**/assets/vrm/models/*`, and the original was a
Tripo scan that is gone from every public branch of the author's
repositories.  What is left in the repository is a placeholder, which is
why the character on the site stands in a T-pose.

So the character is rebuilt out of what the repository does have: the
reference renders in `packages/stage-ui/src/assets/yxz`, the halo, clip and
VRM writers in `scripts/build_yxz_*.py`, and a body mesh reconstructed
from the front reference by Hunyuan3D-2 (`scripts/yxz-rebuild/run_shape.py`).

Two properties of the design drive the whole build.  It is a *pose* and not
a neutral figure -- one arm is raised in a wave and the other hangs down
holding a book -- so the skeleton is measured off the mesh instead of
assumed, and the clips add motion to a pose that is already there.  And
the face is painted into a visor rather than modelled, so the colour comes
from projecting the reference renders back onto the mesh.

Every coordinate below is in the frame the runtime uses: Y up, the
character facing +Z, its own left on +X.  Blender's glTF importer turns
the file into its own Z-up frame, so a landmark (x, y, z) here arrives in
Blender as (x, -z, y); `B()` is that turn.

  blender -b -P scripts/yxz-rebuild/build_yxz_vrm2.py -- \
      --source .run/shape/body_core.glb --output .run/rig/yxz_rig.glb \
      [--texture .run/texture/texture.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SCRIPTS = SCRIPT_DIR.parent


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def B(point):
    """The exported frame -> Blender's frame."""
    return (point[0], -point[2], point[1])


# --------------------------------------------------------------------------
# The skeleton, measured off the mesh.
#
# The body axis sits at x = -0.02: the helmet is wider on the character's
# right than on its left, and the face is therefore a little off the
# midline of the feet.
# --------------------------------------------------------------------------

AXIS = -0.02

SKELETON = [
    # name, head, tail, parent
    ("hips",          (AXIS, 0.42, 0.00), (AXIS, 0.52, 0.00), None),
    ("spine",         (AXIS, 0.52, 0.00), (AXIS, 0.60, 0.00), "hips"),
    ("chest",         (AXIS, 0.60, 0.00), (AXIS, 0.68, 0.00), "spine"),
    ("upperChest",    (AXIS, 0.68, 0.00), (AXIS, 0.78, 0.00), "chest"),
    ("neck",          (AXIS, 0.78, 0.00), (AXIS, 0.86, 0.00), "upperChest"),
    ("head",          (AXIS, 0.86, 0.00), (AXIS, 1.60, 0.00), "neck"),

    # The waving arm.  The shoulder pad is a separate rounded shell, so the
    # clavicle is short and the upper arm points out and slightly down; the
    # elbow sits *below* the shoulder and the forearm comes back up to the
    # raised hand, which is what the reference art shows.
    ("leftShoulder",  (0.14, 0.76, 0.02), (0.24, 0.75, 0.05), "upperChest"),
    ("leftUpperArm",  (0.24, 0.75, 0.05), (0.33, 0.70, 0.13), "leftShoulder"),
    ("leftLowerArm",  (0.33, 0.70, 0.13), (0.48, 0.87, 0.30), "leftUpperArm"),
    ("leftHand",      (0.48, 0.87, 0.30), (0.76, 1.01, 0.37), "leftLowerArm"),

    # The arm carrying the book.  It hangs down and slightly forward, and
    # the book is welded to the hand so that it cannot fold in half.
    ("rightShoulder", (-0.14, 0.76, 0.00), (-0.26, 0.73, -0.02), "upperChest"),
    ("rightUpperArm", (-0.26, 0.73, -0.02), (-0.38, 0.62, -0.02), "rightShoulder"),
    ("rightLowerArm", (-0.38, 0.62, -0.02), (-0.46, 0.47, 0.02), "rightUpperArm"),
    ("rightHand",     (-0.46, 0.47, 0.02), (-0.44, 0.33, 0.10), "rightLowerArm"),

    ("leftUpperLeg",  (0.17, 0.44, 0.00), (0.17, 0.26, 0.00), "hips"),
    ("leftLowerLeg",  (0.17, 0.26, 0.00), (0.19, 0.09, 0.00), "leftUpperLeg"),
    ("leftFoot",      (0.19, 0.09, 0.00), (0.19, 0.03, 0.16), "leftLowerLeg"),
    ("leftToes",      (0.19, 0.03, 0.16), (0.19, 0.02, 0.30), "leftFoot"),
    ("rightUpperLeg", (-0.18, 0.44, 0.00), (-0.18, 0.26, 0.00), "hips"),
    ("rightLowerLeg", (-0.18, 0.26, 0.00), (-0.19, 0.09, 0.00), "rightUpperLeg"),
    ("rightFoot",     (-0.19, 0.09, 0.00), (-0.19, 0.03, 0.16), "rightLowerLeg"),
    ("rightToes",     (-0.19, 0.03, 0.16), (-0.19, 0.02, 0.30), "rightFoot"),

    # The eye bones.  They are pivoted on the visor so that the gaze
    # turns the irises in place instead of swinging them off the face.
    ("leftEye",       (0.11, 1.26, 0.33), (0.09, 1.26, 0.31), "head"),
    ("rightEye",      (-0.15, 1.26, 0.33), (-0.17, 1.26, 0.31), "head"),

    # The halo floats behind and above the helmet, so it hangs off the
    # chest rather than the head; otherwise every head turn swings it
    # across the sky.  The wings get a bone each so they can drift.
    ("halo",          (-0.04, 1.66, -0.02), (-0.04, 1.78, -0.02), "upperChest"),
    ("wing.L",        (0.26, 0.58, -0.12), (0.56, 0.46, -0.12), "upperChest"),
    ("wing.R",        (-0.26, 0.70, -0.12), (-0.62, 0.72, -0.10), "upperChest"),
]

# The vertical chains cannot use a plain distance-to-segment: every bone in
# a vertical stack is the same distance from a point beside it, so a vertex
# on the belly would be split evenly between hips, spine, chest and
# upperChest and the torso would swim when the spine turned.  These bones
# are treated as stacked capsules instead: the vertical gap to the bone's
# own span counts towards the distance.
CAPSULE_BONES = {
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftUpperLeg", "leftLowerLeg", "rightUpperLeg", "rightLowerLeg",
}


def build_armature():
    arm_data = bpy.data.armatures.new("YXZ_Armature")
    arm = bpy.data.objects.new("YXZ_Armature", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    # The bones are made first and given their parents afterwards.
    #
    # Setting a parent on a bone that already has a head and a tail moves
    # the bone: Blender reconnects the child to the parent, so every child
    # ended up folded into its parent -- the eye bones were pulled into the
    # skull and the head bone stopped at the neck.  Parenting first and
    # placing the bones second puts every bone exactly where it was asked
    # for, whatever Blender does to a bone when it gains a parent.
    created = {}
    for name, head, tail, parent in SKELETON:
        bone = arm_data.edit_bones.new(name)
        created[name] = bone

    for name, head, tail, parent in SKELETON:
        bone = created[name]
        bone.use_connect = False
        if parent:
            bone.parent = created[parent]
        bone.head = B(head)
        bone.tail = B(tail)

    bpy.ops.object.mode_set(mode="OBJECT")

    # Read the rig back.  A bone that is not where it was asked for is a
    # rig whose skinning is wrong, and the mistake is invisible until the
    # model is on screen and the arm is somewhere else.
    table = {}
    for name, head, tail, _ in SKELETON:
        bone = arm_data.bones[name]
        want_head = Vector(B(head))
        want_tail = Vector(B(tail))
        if ((bone.head_local - want_head).length > 1e-4
                or (bone.tail_local - want_tail).length > 1e-4):
            raise SystemExit(
                "YXZ_BONE_MISPLACED " + name
                + " head=" + str(tuple(bone.head_local))
                + " tail=" + str(tuple(bone.tail_local))
                + " wanted head=" + str(tuple(want_head))
                + " tail=" + str(tuple(want_tail)))
        table[name] = [round(v, 4) for v in bone.tail_local]
    print("YXZ_BONES " + json.dumps(table))

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


def capsule_distance(points, head, tail):
    """Distance to a vertical stack: sideways gap plus vertical gap."""
    sideways = np.linalg.norm(points[:, [0, 2]] - head[[0, 2]], axis=1)
    low = min(head[1], tail[1])
    high = max(head[1], tail[1])
    gap = np.maximum(np.maximum(low - points[:, 1], points[:, 1] - high), 0.0)
    return np.sqrt(sideways ** 2 + gap ** 2)


def quantise(weights, steps=32):
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


def skin_mesh(mesh_obj, arm, bone_names):
    """Distance-weighted skinning, then the regions that need pinning.

    The distance weighting spreads the blend across each joint instead of
    stepping it, but it cannot be trusted to decide *which* bone owns a
    region: the visor and the raised hand share a volume, and the hand is
    closer to the head bone than to the hand bone unless the hand bone is
    long enough to reach the fingertips.  So the ambiguous regions are
    pinned by hand afterwards.
    """
    count = len(mesh_obj.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh_obj.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)

    usable = [name for name in bone_names
              if name in arm.data.bones
              and not name.endswith(("leftEye", "rightEye"))]
    distances = np.empty((count, len(usable)), dtype=np.float32)
    for index, name in enumerate(usable):
        bone = arm.data.bones[name]
        head = np.array(bone.head_local, dtype=np.float32)
        tail = np.array(bone.tail_local, dtype=np.float32)
        if name in CAPSULE_BONES:
            distances[:, index] = capsule_distance(coords, head, tail)
        else:
            distances[:, index] = segment_distance(coords, head, tail)

    weights = 1.0 / (distances ** 3 + 1e-6)
    # A relative cutoff spreads the blend across the joint.  A hard top-k
    # cut made the shoulder a step: a pauldron vertex jumped from 100%
    # shoulder to 50/50 upper arm within a centimetre and any arm
    # rotation sheared the mesh there.
    weights[weights < weights.max(axis=1, keepdims=True) * 0.06] = 0.0
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-8)

    # The exported frame, which is what the landmarks and the regions
    # below are written in.
    ex = coords[:, 0]
    ey = coords[:, 2]
    ez = -coords[:, 1]

    def pin(mask, bone_name):
        if not mask.any():
            return
        weights[mask, :] = 0.0
        weights[mask, usable.index(bone_name)] = 1.0

    # The book: a flat slab held against the belly.  It sits in front of
    # the forearm, which is what separates it, and it has to be rigid --
    # left to distance weighting its near edge follows the hand while its
    # far edge follows the forearm, and it folds in half.
    pin((ex < -0.22) & (ey > 0.27) & (ey < 0.66) & (ez > 0.04), "rightHand")

    # The wing plates sit at the back where the arms also live.  Pinning
    # them to the chest stops a wave from tearing the wings off the body;
    # they get a bone of their own so the flap can still open a gap at
    # the root.
    wing_right = (ex < -0.30) & (ey > 0.50) & (ez < 0.06)
    pin(wing_right, "wing.R")
    wing_left = (ex > 0.30) & (ey > 0.40) & (ey < 0.72) & (ez < 0.02)
    pin(wing_left, "wing.L")

    # The helmet.  The raised hand is inside the same volume as the head,
    # so it is taken out first: it is the one thing that would otherwise
    # be closer to the head bone than to the arm.
    raised_hand = (ex > 0.47) & (ey > 0.86)
    pin(raised_hand & (ey > 0.93), "leftHand")
    pin((ey > 0.86) & ~raised_hand, "head")

    units = quantise(weights)

    # Write the weights in batches: one call per bone and weight level,
    # rather than one call per vertex.
    groups = mesh_obj.vertex_groups
    for index, name in enumerate(usable):
        group = groups.new(name=name)
        column = units[:, index]
        for level in range(1, int(units.max()) + 1):
            if level > column.max():
                break
            indices = np.flatnonzero(column == level).tolist()
            if indices:
                group.add(indices, level / float(units.max()), "REPLACE")

    report = {
        "bones": len(usable),
        "vertices": count,
        "pinned": {
            "book": int(((ex < -0.22) & (ey > 0.27) & (ey < 0.66)
                         & (ez > 0.04)).sum()),
            "wingR": int(wing_right.sum()),
            "wingL": int(wing_left.sum()),
            "head": int(((ey > 0.86) & ~raised_hand).sum()),
            "hand": int((raised_hand & (ey > 0.93)).sum()),
        },
    }
    return report


def build_halo(arm):
    """The halo as a ring of light, reusing the repository's own builder."""
    sys.path.insert(0, str(REPO_SCRIPTS))
    import rebuild_yxz_halo as constants

    # The builder works in the old scan's frame (Z up, the character facing
    # +X) and turns its constants into the exported frame itself.  The
    # ring on this model is a little wider and a little lower than the
    # scan's, so the constants are replaced with measured ones.
    # The centre is given in the builder's own frame, which is Z up and
    # has the character facing +X; `R()` turns it into Blender's frame.
    # Up is the third component of that frame, so the ring's height goes
    # in the third component and not the first: read as a horizontal
    # coordinate it put the halo on the floor at the character's feet.
    constants.CENTRE = Vector((-0.02, -0.02, 1.66))
    constants.RADIUS = 0.355
    constants.WIDTH = 0.030
    constants.DEPTH = 0.010
    constants.STAR_OUTER = 0.070
    constants.STAR_INNER = 0.030
    constants.STAR_DEPTH = 0.012

    from build_yxz_halo import attach_halo

    return attach_halo(arm)


def lookat_offset(arm):
    """Where the face is, relative to the head bone."""
    head = np.array(arm.data.bones["head"].head_local, dtype=np.float64)
    # The visor sits on the front of the helmet, about a third of the way
    # up it.  The offset is measured in Blender's frame, because that is
    # the frame the head bone's own position is in: mixing the two put the
    # gaze a whole head-height away from the face.
    face = np.array(B((AXIS, 1.24, 0.34)), dtype=np.float64)
    return [float(v) for v in (face - head)]


def export_glb(output):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        if obj.type in {"MESH", "ARMATURE"}:
            obj.select_set(True)
    bpy.context.view_layer.objects.active = next(
        obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
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


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh in " + str(source))
    mesh_obj = max(meshes, key=lambda obj: len(obj.data.vertices))

    # The paint, if there is any: the reference renders projected back onto
    # the model, so the character is the colour the artist drew rather
    # than the grey of a reconstruction.
    paint_dir = value_after("--paint")
    if paint_dir:
        sys.path.insert(0, str(SCRIPT_DIR))
        from bake_paint import apply_paint, strip_debris

        print("YXZ_DEBRIS " + str(strip_debris(mesh_obj)))
        print("YXZ_PAINT_REPORT "
              + json.dumps(apply_paint(mesh_obj, Path(paint_dir))))

    arm, edit_bones = build_armature()
    report = skin_mesh(mesh_obj, arm, list(edit_bones.keys()))
    print("YXZ_SKIN " + json.dumps(report))

    if "--no-halo" not in sys.argv:
        print("YXZ_HALO " + json.dumps(build_halo(arm)))

    if "--no-clips" not in sys.argv:
        sys.path.insert(0, str(REPO_SCRIPTS))
        from build_yxz_clips import add_clips

        add_clips(arm)

    offset = lookat_offset(arm)
    output.with_suffix(".lookat.json").write_text(
        json.dumps({"offsetFromHeadBone": offset}), encoding="utf-8")

    export_glb(output)
    print("YXZ_BUILT " + str(output))


if __name__ == "__main__":
    main()
