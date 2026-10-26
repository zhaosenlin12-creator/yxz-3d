"""Measure how broken the YXZ normals are.

The character's face reads as shattered: a row of saw-tooth triangles runs
along the jaw and a band of speckle runs along the top of the visor.  The
geometry and the base colour atlas are both clean -- a flat unlit render
shows a smooth silhouette and a smooth texture -- so what is left is the
normals.  Where the normals are noisy, MToon's cel ramp turns every
neighbouring triangle into a different shade, and a smooth surface comes
out looking like a torn one.

This measures the two things that matter:

  edge angle     the angle between the two faces meeting at an edge.  A
                 smooth surface keeps these small; a faceted one keeps them
                 large.
  normal drift   the angle between a vertex's stored normal and the
                 average of the faces around it.  This is the number that
                 goes wrong when a mesh is welded or merged: the position
                 ends up averaged but the normal does not.

Usage:
  blender -b -P scripts/probe_yxz_normals.py -- --source <glb> [--head-z 0.15]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def main():
    source = Path(value_after("--source"))
    head_z = float(value_after("--head-z", 0.15))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh in " + str(source))
    body = max(meshes, key=lambda obj: len(obj.data.vertices))
    mesh = body.data

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()

    sharp_edges = 0
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            edge.smooth = edge.calc_face_angle(0.0) < math.radians(40.0)
            if not edge.smooth:
                sharp_edges += 1
        else:
            edge.smooth = True
    flat_faces = sum(1 for face in bm.faces if not face.smooth)

    head_verts = [v for v in bm.verts if v.co.z > head_z]
    head_faces = [f for f in bm.faces if f.calc_center_median().z > head_z]
    head_edges = [e for e in bm.edges
                  if (e.verts[0].co.z + e.verts[1].co.z) * 0.5 > head_z
                  and len(e.link_faces) == 2]

    edge_angles = [e.calc_face_angle(0.0) for e in head_edges]
    drift = []
    for vert in head_verts:
        faces = vert.link_faces
        if not faces:
            continue
        average = Vector((0.0, 0.0, 0.0))
        for face in faces:
            average += face.normal * face.calc_area()
        if average.length < 1e-9:
            continue
        average.normalize()
        drift.append(vert.normal.angle(average))

    report = {
        "source": str(source),
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "sharp_edges_over_40deg": sharp_edges,
        "flat_faces": flat_faces,
        "head": {
            "threshold_z": head_z,
            "vertices": len(head_verts),
            "polygons": len(head_faces),
            "edges": len(head_edges),
            "edge_angle_deg": {
                "p50": round(math.degrees(percentile(edge_angles, 0.50)), 2),
                "p90": round(math.degrees(percentile(edge_angles, 0.90)), 2),
                "p99": round(math.degrees(percentile(edge_angles, 0.99)), 2),
                "max": round(math.degrees(max(edge_angles)) if edge_angles else 0.0, 2),
            },
            "normal_drift_deg": {
                "p50": round(math.degrees(percentile(drift, 0.50)), 2),
                "p90": round(math.degrees(percentile(drift, 0.90)), 2),
                "p99": round(math.degrees(percentile(drift, 0.99)), 2),
                "max": round(math.degrees(max(drift)) if drift else 0.0, 2),
            },
        },
    }
    bm.free()
    print("YXZ_NORMALS " + json.dumps(report))


if __name__ == "__main__":
    main()
