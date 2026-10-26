"""Render the faces that could be the halo, on their own.

The halo is the only part of the character painted a saturated cyan,
but cyan also appears on the eyes, the wrist bands and the boot tips,
so the colour alone does not identify it.  Isolating the candidates
and photographing them from above and from the front is the quickest
way to see what the geometry actually is.

Usage:
  blender -b -P scripts/probe_yxz_halo_candidates.py -- \
    --glb <glb> --out <dir> [--min-z 0.40] [--threshold 0.0015]
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild_yxz_halo import is_cyan, load_atlas  # noqa: E402


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def render(objects, out_path, location, rotation, scale, size=700):
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in objects:
        if obj.name not in scene.collection.objects:
            scene.collection.objects.link(obj)

    cam_data = bpy.data.cameras.new("probe")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("probe", cam_data)
    scene.collection.objects.link(cam)
    cam.location = Vector(location)
    cam.rotation_euler = rotation
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.2, 0.4)

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out")).resolve()
    min_z = float(value_after("--min-z", 0.40))
    threshold = float(value_after("--threshold", 0.0015))
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    atlas = load_atlas()
    height, width = atlas.shape[0], atlas.shape[1]

    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh = body.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_bm = bm.loops.layers.uv.active
    keep = []
    for face in bm.faces:
        if face.calc_center_median().z < min_z:
            continue
        u = sum(loop[uv_bm].uv.x for loop in face.loops) / len(face.loops)
        v = sum(loop[uv_bm].uv.y for loop in face.loops) / len(face.loops)
        x = int(min(max(u, 0.0), 1.0) * (width - 1))
        y = int(min(max(v, 0.0), 1.0) * (height - 1))
        if is_cyan(atlas[y, x]):
            keep.append(face)
    print("YXZ_CANDIDATES %d" % len(keep))
    # The height distribution of the cyan faces, so the halo's own
    # extent can be read off: it is the only cyan up at the top.
    histogram = {}
    for face in keep:
        bucket = round(face.calc_center_median().z, 1)
        histogram[bucket] = histogram.get(bucket, 0) + 1
    print("YXZ_CYAN_Z " + repr(sorted(histogram.items())))

    copy = mesh.copy()
    keep_bm = bmesh.new()
    keep_bm.from_mesh(copy)
    keep_ids = set(f.index for f in keep)
    doomed = [f for f in keep_bm.faces if f.index not in keep_ids]
    bmesh.ops.delete(keep_bm, geom=doomed, context="FACES")
    keep_bm.to_mesh(copy)
    keep_bm.free()
    obj = bpy.data.objects.new("candidates", copy)
    bpy.context.scene.collection.objects.link(obj)

    # The candidates in their own colour, with the rest of the model in
    # grey behind them, so it is obvious where they are.
    for target, colour in ((obj, (0.9, 0.1, 0.7)), (body, (0.55, 0.58, 0.62))):
        target.data.materials.clear()
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
            colour[0], colour[1], colour[2], 1.0)
        material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
        target.data.materials.append(material)

    import math
    # From above, and from the front.
    render([obj, body], out / "candidates-top.png", (0.0, 0.0, 2.0),
           (0.0, 0.0, 0.0), 1.05)
    render([obj, body], out / "candidates-front.png", (0.0, -2.0, 0.0),
           (math.radians(90.0), 0.0, 0.0), 1.05)
    render([obj, body], out / "candidates-side.png", (-2.0, 0.0, 0.0),
           (math.radians(90.0), 0.0, math.radians(90.0)), 1.05)
    render([obj, body], out / "candidates-front2.png", (0.0, 2.0, 0.0),
           (math.radians(90.0), 0.0, math.radians(180.0)), 1.05)
    print("YXZ_RENDERED " + str(out))
    bm.free()


if __name__ == "__main__":
    main()
