"""Which faces are turned the wrong way round, and where they are.

The dark patches on the shell are not holes -- the shell is watertight --
and they are not in the texture either, because they survive a flat white
render.  What is left is that the faces under them point inwards, so the
light lands on their backs and they read as holes punched through the
helmet.

The test does not assume the shell is convex.  Every face is measured
against the middle of the body: on the outside of a head the normal points
away from that middle, and a face whose normal has been flipped points the
other way.

Usage:
  blender -b -P scripts/probe_yxz_flipped.py -- --glb <glb> [--top 12]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def clusters(faces):
    """Group flipped faces that touch, so a patch is reported as a patch."""
    by_index = {face.index: face for face in faces}
    remaining = set(by_index)
    by_vertex = {}
    for index, face in by_index.items():
        for vertex in face.verts:
            by_vertex.setdefault(vertex.index, []).append(index)
    out = []
    while remaining:
        seed = remaining.pop()
        group = [seed]
        stack = [seed]
        while stack:
            current = stack.pop()
            for vertex in by_index[current].verts:
                for neighbour in by_vertex.get(vertex.index, ()):
                    if neighbour in remaining:
                        remaining.discard(neighbour)
                        group.append(neighbour)
                        stack.append(neighbour)
        points = np.array([[c for v in by_index[i].verts for c in v.co] for i in group])
        low = points.min(axis=0)
        high = points.max(axis=0)
        out.append({
            "faces": len(group),
            "span": [round(float(high[axis] - low[axis]), 4) for axis in range(3)],
            "centre": [round(float((low[axis] + high[axis]) / 2), 3) for axis in range(3)],
        })
    out.sort(key=lambda row: -row["faces"])
    return out


def main():
    source = value_after("--glb")
    top = int(value_after("--top", 12))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    report = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not len(obj.data.polygons):
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.index_update()
        bm.normal_update()
        every = np.array([c for vertex in bm.verts for c in vertex.co])
        origin = every.reshape(-1, 3).mean(axis=0)
        flipped = []
        for face in bm.faces:
            centre = np.array(face.calc_center_median())
            if float(np.dot(np.array(face.normal), centre - origin)) < 0.0:
                flipped.append(face)
        groups = clusters(flipped) if flipped else []
        report.append({
            "mesh": obj.name,
            "faces": len(bm.faces),
            "flipped": len(flipped),
            "flippedPct": round(100.0 * len(flipped) / max(1, len(bm.faces)), 2),
            "groups": len(groups),
            "top": groups[:top],
        })
        bm.free()

    report.sort(key=lambda row: -row["flipped"])
    print("YXZ_FLIPPED " + json.dumps(report))


main()
