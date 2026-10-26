"""Add stable open-eye geometry to the YXZ face-control GLB.

The Tripo visor texture has a dark baked eye area. The existing blink meshes
are useful as closed lids, but they are not a reliable open-eye state after
glTF transform baking. This script adds small white eye plates that the
runtime can show/hide without scaling the character or its skin.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import bpy


def material(name: str, color: tuple[float, float, float, float]):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.14
        # The reference character uses luminous cyan oval eye lights rather
        # than white eyeballs with dark pupils.  Keep this as a material-level
        # treatment so the silhouette stays rigid and the eye layer remains
        # independently hideable for blinking.
        emission = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission:
            emission.default_value = (0.015, 0.48, 1.0, 1.0)
        strength = bsdf.inputs.get("Emission Strength")
        if strength:
            strength.default_value = 1.8
    return mat


def add_eye(name: str, y: float, mat, armature) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32,
        ring_count=16,
        location=(0.279, y, 0.18),
    )
    obj = bpy.context.object
    obj.name = name
    # Slightly taller than wide to match the cyan vertical eye ovals in the
    # supplied YXZ reference, while keeping the plate fully inside the visor.
    obj.scale = (0.009, 0.034, 0.048)
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

    eye_mat = material("YXZ_EyeOpen", (0.03, 0.64, 0.98, 1.0))
    eyes = [
        add_eye("YXZ_FaceEyeOpen.L", -0.095, eye_mat, armature),
        add_eye("YXZ_FaceEyeOpen.R", 0.095, eye_mat, armature),
    ]
    for eye in eyes:
        eye.hide_render = False

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
    print("open eye controls written", [eye.name for eye in eyes], "to", args.output)


if __name__ == "__main__":
    main()
