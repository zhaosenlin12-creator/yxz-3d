"""Validate whether a GLB is safe to use as an animated YXZ avatar.

This is intentionally conservative: a single skinned mesh without morph
targets or named eye joints is reported as body-motion blocked. Face-control
meshes are not joints and must never satisfy the eye-joint check.

Tiering measures coverage of the VRM 1.0 *required* humanoid bones rather
than raw joint count. AIRI's own girl carries 91 joints because she has
fingers and facial bones; a rig that omits those is still a fully valid
humanoid, so a fixed joint-count threshold would misreport a correct rig as
incomplete.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

# VRM 1.0 requires these; anything else (shoulders, toes, upperChest, fingers)
# is an optional refinement.
REQUIRED_HUMANOID_BONES = (
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftEye", "rightEye",
)

VRM_PRESET_EXPRESSIONS = (
    "happy", "angry", "sad", "relaxed", "surprised",
    "aa", "ih", "ou", "ee",
    "blink", "blinkLeft", "blinkRight",
)


def read_gltf_json(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB file")
    position = 12
    while position < len(data):
        length, chunk_type = struct.unpack_from("<II", data, position)
        position += 8
        chunk = data[position:position + length]
        position += length
        if chunk_type == 0x4E4F534A:
            return json.loads(chunk.decode("utf-8"))
    raise ValueError("JSON chunk not found")


def validate(path: Path) -> dict:
    document = read_gltf_json(path)
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    named_nodes = [node.get("name", "") for node in nodes if node.get("name")]
    joint_indices = {
        joint
        for skin in document.get("skins", [])
        for joint in skin.get("joints", [])
    }
    eye_bones = [
        nodes[index].get("name", "")
        for index in sorted(joint_indices)
        if index < len(nodes)
        and any(token in nodes[index].get("name", "").lower() for token in ("eye", "iris", "pupil"))
    ]
    face_control_nodes = [
        name for name in named_nodes
        if any(token in name.lower() for token in ("faceblink", "faceeye", "facemouth"))
    ]
    morph_targets = sum(
        len(primitive.get("targets", []))
        for mesh in meshes
        for primitive in mesh.get("primitives", [])
    )
    animations = [
        {"name": animation.get("name", "unnamed"), "channels": len(animation.get("channels", []))}
        for animation in document.get("animations", [])
    ]
    # three-vrm picks its reader by the extension's *name*: a VRM 1.0 body
    # filed under `extensions.VRM` is read as a 0.x asset, which quietly
    # drops the expression bindings and the look-at head offset.  Prefer
    # `VRMC_vrm` and report which one was actually found.
    all_extensions = document.get("extensions", {})
    extension_name = ""
    vrm_extensions = {}
    for candidate in ("VRMC_vrm", "VRM"):
        if all_extensions.get(candidate):
            extension_name = candidate
            vrm_extensions = all_extensions[candidate]
            break
    declared = [name for name in ("VRMC_vrm", "VRM")
                if name in document.get("extensionsUsed", [])]
    extension_mismatch = sorted(set(declared) - {extension_name}) if extension_name else declared
    joint_count = len(joint_indices)

    human_bones = []
    if vrm_extensions:
        raw_bones = vrm_extensions.get("humanoid", {}).get("humanBones", {})
        if isinstance(raw_bones, dict):
            # VRM 1.0 keys the map by bone name.
            human_bones = list(raw_bones.keys())
        else:
            # VRM 0.x used an array of {bone, node} entries.
            human_bones = [entry.get("bone") for entry in raw_bones]
    missing_required = [bone for bone in REQUIRED_HUMANOID_BONES
                        if bone not in human_bones]

    expression_names = set()
    if vrm_extensions:
        for group in vrm_extensions.get("expressions", {}).values():
            if isinstance(group, dict):
                expression_names.update(group.keys())
    missing_presets = [name for name in VRM_PRESET_EXPRESSIONS
                       if name not in expression_names]

    # A useful AIRI-style candidate needs the VRM contract, a substantial
    # humanoid skeleton, and real facial morphs. Face-control meshes alone are
    # deliberately classified as a rendering facade, never as a full avatar.
    complete_humanoid = bool(vrm_extensions) and not missing_required
    if complete_humanoid and not missing_presets and morph_targets >= 20:
        quality_tier = "vrm-expression-ready"
    elif complete_humanoid or morph_targets >= 20 or eye_bones:
        quality_tier = "facial-rig-candidate"
    else:
        quality_tier = "facade-only"
    safe_for_body_motion = quality_tier != "facade-only"
    return {
        "file": str(path),
        "skins": len(document.get("skins", [])),
        "jointCount": joint_count,
        "humanoidBones": len(human_bones),
        "missingRequiredBones": missing_required,
        "missingPresetExpressions": missing_presets,
        "morphTargetSets": morph_targets,
        "eyeBones": eye_bones,
        "faceControlNodes": face_control_nodes,
        "animations": animations,
        "vrm": bool(vrm_extensions),
        "vrmExtension": extension_name or None,
        "extensionMismatch": extension_mismatch,
        "qualityTier": quality_tier,
        "bodyMotion": "allow" if safe_for_body_motion else "block",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("glb", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.glb), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
