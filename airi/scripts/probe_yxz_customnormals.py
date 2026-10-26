"""Check how the YXZ normals are stored inside Blender.

The glTF importer can hand Blender either plain vertex normals or custom
split normals.  The difference decides how the mesh can be repaired: a
vertex normal that is edited on a mesh with custom split normals changes
nothing, because the split normals are what the exporter writes out.

Usage:
  blender -b -P scripts/probe_yxz_customnormals.py -- --source <glb>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main():
    source = Path(value_after("--source"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    body = max(meshes, key=lambda obj: len(obj.data.vertices))
    mesh = body.data

    report = {
        "source": str(source),
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "has_custom_normals_attr": hasattr(mesh, "has_custom_normals"),
        "has_custom_normals": getattr(mesh, "has_custom_normals", None),
        "has_corner_normals": hasattr(mesh, "corner_normals"),
        "has_normals_split_custom_set": hasattr(mesh, "normals_split_custom_set"),
        "has_normals_split_custom_set_from_vertices":
            hasattr(mesh, "normals_split_custom_set_from_vertices"),
        "attributes": sorted(a.name for a in mesh.attributes),
    }

    bm = bmesh.new()
    bm.from_mesh(mesh)
    report["bmesh_loop_layers"] = list(bm.loops.layers.keys())
    report["bmesh_vertex_layers"] = list(bm.verts.layers.keys())
    bm.free()

    # How far is each corner normal from the vertex normal it belongs to?
    # A mesh that stores split normals has a large spread here; a mesh that
    # stores plain vertex normals has almost none.
    try:
        corner_normals = list(mesh.corner_normals)
        spread = []
        for loop in mesh.loops:
            vertex = mesh.vertices[loop.vertex_index]
            spread.append((corner_normals[loop.index].vector - vertex.normal).length)
        spread.sort()
        report["corner_vs_vertex"] = {
            "p50": round(spread[len(spread) // 2], 5),
            "p90": round(spread[int(len(spread) * 0.9)], 5),
            "max": round(spread[-1], 5),
        }
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not fail
        report["corner_vs_vertex_error"] = str(error)

    print("YXZ_CUSTOMNORMALS " + json.dumps(report))


if __name__ == "__main__":
    main()
