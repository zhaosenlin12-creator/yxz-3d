"""Inspect the current YXZ GLB: bones, weights, topology, face-region extent.

Run headless:
  blender -b -P scripts/inspect_yxz_asset.py -- --glb <path>

Everything is printed as JSON so the numbers can be diffed across rebuilds.
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def count_action_fcurves(action) -> int:
    """Blender 5.x moved fcurves into per-slot channelbags."""
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return len(legacy)
    total = 0
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                total += len(bag.fcurves)
    return total


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]

    report: dict = {
        "glb": glb,
        "meshCount": len(meshes),
        "armatureCount": len(armatures),
        "meshes": [],
        "bones": [],
        "actions": [],
    }

    for mesh in meshes:
        entry = {
            "name": mesh.name,
            "vertices": len(mesh.data.vertices),
            "polygons": len(mesh.data.polygons),
            "shapeKeys": [k.name for k in (mesh.data.shape_keys.key_blocks if mesh.data.shape_keys else [])],
            "vertexGroups": [g.name for g in mesh.vertex_groups],
            "parent": mesh.parent.name if mesh.parent else None,
            "matrixWorld": [[round(v, 5) for v in row] for row in mesh.matrix_world],
        }
        if entry["vertices"]:
            xs = [v.co.x for v in mesh.data.vertices]
            ys = [v.co.y for v in mesh.data.vertices]
            zs = [v.co.z for v in mesh.data.vertices]
            entry["bounds"] = {
                "x": [min(xs), max(xs)],
                "y": [min(ys), max(ys)],
                "z": [min(zs), max(zs)],
            }
        # World-space bounds tell us where a part actually sits in the body,
        # which is more useful than local bounds for placed overlay geometry.
        report["meshes"].append(entry)

    for armature in armatures:
        for bone in armature.data.bones:
            report["bones"].append(
                {
                    "name": bone.name,
                    "parent": bone.parent.name if bone.parent else None,
                    "head": [round(v, 4) for v in bone.head_local],
                    "tail": [round(v, 4) for v in bone.tail_local],
                }
            )
        for action in bpy.data.actions:
            report["actions"].append(
                {"name": action.name, "fcurves": count_action_fcurves(action)}
            )

    print("YXZ_INSPECT " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
