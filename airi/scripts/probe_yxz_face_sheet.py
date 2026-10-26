"""
 * Find the flat sheet lying across the face.
 *
 * The bright streak on the visor is not paint.  A ray that lands on it
 * hits a surface that is perfectly flat -- every point of it sits at the
 * same depth -- and it hits that surface three times over at the same
 * depth, which is why the streak reads as a dashed line rather than a
 * smooth one.  Flat means it is a sheet, and a sheet across the face is
 * a piece of the scan that is standing where it should not.
 *
 * So this splits the mesh into its connected shells and prints the ones
 * that are flat and that lie in front of the face, and photographs each
 * of them on its own.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_face_sheet.py -- \
 *     --glb <glb> --out <dir> [--point x,y,z] [--front 0.30]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """The connected components of a bmesh, as lists of faces."""
    bm.faces.ensure_lookup_table()
    unseen = set(bm.faces)
    groups = []
    while unseen:
        seed = unseen.pop()
        group = [seed]
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour in unseen:
                        unseen.discard(neighbour)
                        group.append(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    groups.sort(key=lambda group: -len(group))
    return groups


def render(objects, out_path, center, scale, size=700, yaw=0.0):
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
    cam.location = Vector((center[0], center[1], 2.0))
    cam.rotation_euler = (0.0, 0.0, yaw)
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
    point = [float(part) for part in value_after("--point", "0,0,0").split(",")]
    front = float(value_after("--front", "0.30"))
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    mesh = body.data

    bm = bmesh.new()
    bm.from_mesh(mesh)
    groups = shells(bm)

    all_points = np.array([tuple(v.co) for v in bm.verts])
    lo = all_points.min(axis=0)
    hi = all_points.max(axis=0)
    print("YXZ_SHEET_BBOX " + json.dumps({"min": lo.tolist(), "max": hi.tolist()}))

    records = []
    for index, group in enumerate(groups):
        points = np.array([tuple(v.co) for v in {
            v for face in group for v in face.verts
        }])
        group_lo = points.min(axis=0)
        group_hi = points.max(axis=0)
        extent = group_hi - group_lo
        area = sum(face.calc_area() for face in group)
        # The sheet's own spread along its three axes, in the order of the
        # axes themselves: a sheet is thin along one of them.
        record = {
            "index": index,
            "faces": len(group),
            "area": round(area, 6),
            "min": [round(float(v), 4) for v in group_lo],
            "max": [round(float(v), 4) for v in group_hi],
            "extent": [round(float(v), 4) for v in extent],
        }
        records.append(record)
        print("YXZ_SHEET " + json.dumps(record))

    # The point the ray hit, and the shells that hold it.
    target = Vector(point)
    nearest = []
    for index, group in enumerate(groups):
        best = min(
            (v.co - target for v in {v for face in group for v in face.verts}),
            key=lambda delta: delta.length,
        )
        nearest.append((best.length, index))
    nearest.sort()
    print("YXZ_SHEET_NEAREST " + json.dumps([{"distance": round(d, 4), "index": i} for d, i in nearest[:6]]))

    (out / "shells.json").write_text(json.dumps(records, indent=1))

    # Photograph the shells that lie in front of the face on their own.
    for distance, index in nearest[:3]:
        group = groups[index]
        points = np.array([tuple(v.co) for v in {v for face in group for v in face.verts}])
        center = ((points.min(axis=0) + points.max(axis=0)) / 2).tolist()
        extent = points.max(axis=0) - points.min(axis=0)
        scale = float(max(extent.max(), 0.05)) * 1.4
        faces = set(group)
        scene = bpy.context.scene
        for obj in list(scene.objects):
            if obj.type == "MESH":
                bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=glb)
        body = max(
            (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
            key=lambda obj: len(obj.data.vertices),
        )
        bm = bmesh.new()
        bm.from_mesh(body.data)
        doomed = [face for face in bm.faces if face.index not in {
            f.index for f in shells(bm)[index]
        }]
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(body.data)
        bm.free()
        render([body], out / f"shell-{index}-d{distance:.4f}.png", center, scale)
        print(f"YXZ_SHEET_RENDERED shell-{index}-d{distance:.4f}.png center={center} scale={scale:.4f}")


if __name__ == "__main__":
    main()
