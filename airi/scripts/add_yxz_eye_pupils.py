"""Add stable pupils to the YXZ open-eye control layer."""

from __future__ import annotations

import argparse
from pathlib import Path

import bpy


def make_material(name: str, color: tuple[float, float, float, float]):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = 0.05
        bsdf.inputs["Roughness"].default_value = 0.18
    return mat


def add_pupil(name: str, y: float, mat, armature) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=24,
        ring_count=12,
        location=(0.285, y, 0.18),
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = (0.0045, 0.018, 0.015)
    obj.data.materials.append(mat)
    obj.parent = armature
    return obj


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    import sys
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(script_args)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("No armature found in rigged model")

    pupil_mat = make_material("YXZ_EyePupil", (0.015, 0.065, 0.16, 1.0))
    pupils = [
        add_pupil("YXZ_FaceEyePupil.L", -0.095, pupil_mat, armature),
        add_pupil("YXZ_FaceEyePupil.R", 0.095, pupil_mat, armature),
    ]
    for pupil in pupils:
        pupil.hide_render = False

    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.with_suffix(".blend")))
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        export_apply=False,
        export_animations=True,
        export_skins=True,
        export_morph=True,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
    )
    print("pupil controls written", [pupil.name for pupil in pupils], "to", args.output)


if __name__ == "__main__":
    main()
