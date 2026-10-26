"""Add non-skinned closed/open mouth layers to the YXZ GLB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def material(name: str, color: tuple[float, float, float, float], roughness: float = 0.3):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def add_open_mouth(armature: bpy.types.Object) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=(0.282, 0.0, 0.058))
    mouth = bpy.context.object
    mouth.name = "YXZ_FaceMouthOpen"
    mouth.scale = (0.006, 0.041, 0.022)
    mouth.data.materials.append(material("YXZ_MouthInterior", (0.012, 0.008, 0.022, 1.0), roughness=0.25))
    mouth.parent = armature
    return mouth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("YXZ armature was not found")
    if bpy.data.objects.get("YXZ_FaceMouthOpen") is None:
        add_open_mouth(armature)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_apply=False,
        export_animations=True,
        export_skins=True,
        export_morph=True,
        export_nla_strips=True,
        export_anim_single_armature=True,
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
    )
    print(f"mouth viseme asset written to {args.output}")


if __name__ == "__main__":
    main()
