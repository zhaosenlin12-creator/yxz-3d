"""Add lightweight, animation-ready face controls to the YXZ rig.

The Tripo mesh is a single textured surface without morph targets.  This
script adds small geometry layers in front of the visor so runtime code can
control blinking and mouth visibility without pretending the source mesh has
native facial morphs.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import bpy
from mathutils import Vector


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load_glb(path: Path) -> None:
    bpy.ops.import_scene.gltf(filepath=str(path))


def material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0, roughness: float = 0.35):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def add_uv_sphere(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    armature,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    # Keep the control in the same model space as the rig.  The armature
    # object is the stable parent while its bones continue animating the mesh.
    obj.parent = armature
    return obj


def add_smile(name: str, x: float, mat, armature) -> bpy.types.Object:
    curve_data = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 3
    curve_data.bevel_depth = 0.006
    curve_data.bevel_resolution = 3
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(2)
    # Coordinates are in model space: x is depth, y is left/right, z is up.
    points = ((x, -0.045, 0.065), (x, 0.0, 0.045), (x, 0.045, 0.065))
    for point, co in zip(spline.bezier_points, points):
        point.co = co
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(obj)
    curve_data.materials.append(mat)
    obj.parent = armature
    return obj


def add_controls() -> list[bpy.types.Object]:
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("No armature found in rigged model")

    # The imported Tripo model is normalized to a one-unit Z-up character.
    # The visor front is +X; these coordinates were verified against the
    # rendered model rather than guessed from the runtime camera.
    visor = material("YXZ_VisorControl", (0.005, 0.025, 0.095, 1.0), metallic=0.15, roughness=0.22)
    mouth = material("YXZ_MouthControl", (0.95, 0.22, 0.35, 1.0), metallic=0.0, roughness=0.32)

    controls: list[bpy.types.Object] = []
    # Closed-eye masks are hidden by scale in the open state and expanded by
    # runtime during a blink.  Keeping them as separate objects makes the
    # behaviour explicit and robust across Three.js and Blender importers.
    left_lid = add_uv_sphere("YXZ_FaceBlink.L", (0.267, -0.095, 0.18), (0.008, 0.055, 0.045), visor, armature)
    right_lid = add_uv_sphere("YXZ_FaceBlink.R", (0.267, 0.095, 0.18), (0.008, 0.055, 0.045), visor, armature)
    # Start open.  Runtime sets local Z scale to 1.0 for a closed blink.
    left_lid.scale.z = 0.001
    right_lid.scale.z = 0.001
    controls.extend((left_lid, right_lid))
    # A visor-coloured patch hides the baked smile; the curve below becomes a
    # controllable mouth line and can be scaled vertically while speaking.
    controls.append(add_uv_sphere("YXZ_FaceMouthCover", (0.267, 0.0, 0.065), (0.008, 0.052, 0.032), visor, armature))
    controls.append(add_smile("YXZ_FaceMouth", 0.276, mouth, armature))
    return controls


def export_glb(path: Path) -> None:
    bpy.ops.wm.save_as_mainfile(filepath=str(path.with_suffix(".blend")))
    bpy.ops.export_scene.gltf(
        filepath=str(path),
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    # Blender keeps its own flags in sys.argv; only parse arguments after the
    # conventional `--` separator passed to the Python script.
    import sys

    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(script_args)
    clear_scene()
    load_glb(args.input)
    controls = add_controls()
    print("FACE_CONTROLS", [obj.name for obj in controls])
    export_glb(args.output)
    print(f"exported {args.output}")


if __name__ == "__main__":
    main()
