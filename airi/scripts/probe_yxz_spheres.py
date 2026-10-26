"""Fit the helmet's bubble and the head inside it, robustly.

The bubble came back from the scan as a handful of large panels and a
drift of fragments, and the panels are all parts of one spherical
surface.  Fitting that surface tells the bubble's size and place
exactly, which is what a clean replacement for the shattered part has
to agree with.

The fit is robust because the panels are not all one surface: the
forehead plate is nearly flat where it meets the face, and a plain
least squares fit is dragged off by it.  Points that disagree with
the fit are dropped and the fit is repeated, which is how the sphere
is recovered from a set of pieces that only mostly agree.

Usage:
  blender -b -P scripts/probe_yxz_spheres.py -- --glb <glb> \
    [--panels 3178,3150,3252,3487] [--body-out <glb>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    bm.faces.ensure_lookup_table()
    groups = []
    unvisited = set(bm.faces)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        groups.append(group)
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def fit_sphere(points):
    """The sphere that best fits a set of points (Kasa's method)."""
    x = points[:, 0]
    y = points[:, 1]
    z = points[:, 2]
    matrix = np.column_stack([2 * x, 2 * y, 2 * z, np.ones(len(points))])
    target = x ** 2 + y ** 2 + z ** 2
    solution, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    centre = solution[:3]
    radius = float(np.sqrt(solution[3] + centre @ centre))
    return centre, radius


def robust_fit(points, passes=6):
    """Fit a sphere, dropping the points that disagree with it."""
    keep = np.ones(len(points), dtype=bool)
    centre, radius = fit_sphere(points)
    outliers = 0
    for _ in range(passes):
        distance = np.linalg.norm(points[keep] - centre, axis=1)
        error = np.abs(distance - radius)
        limit = max(float(np.percentile(error, 75)) * 2.5, 1e-5)
        inner = error <= limit
        outliers = int((~inner).sum())
        new_keep = np.zeros(len(points), dtype=bool)
        new_keep[np.where(keep)[0][inner]] = True
        if new_keep.sum() < 32 or not inner.any():
            break
        centre, radius = fit_sphere(points[new_keep])
        keep = new_keep
    return centre, radius, keep, outliers


def main() -> None:
    glb = Path(value_after("--glb"))
    panels = [
        int(piece)
        for piece in value_after("--panels", "3178,3150,3252,3487").split(",")
        if piece.strip()
    ]
    body_out = value_after("--body-out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)
    body_group = max(groups, key=len)

    def group_points(number):
        return np.array([
            list(vertex.co)
            for face in groups[number]
            for vertex in face.verts
        ])

    def report(name, points):
        centre, radius, keep, outliers = robust_fit(points)
        distance = np.linalg.norm(points[keep] - centre, axis=1)
        return {
            "name": name,
            "inliers": int(keep.sum()),
            "total": int(len(points)),
            "outliers": outliers,
            "centre": [round(float(value), 4) for value in centre],
            "radius": round(radius, 4),
            "deviation": round(float(distance.std()), 5),
            "worst": round(float(distance.max()), 5),
        }

    rows = []
    for number in panels:
        rows.append(report("panel%d" % number, group_points(number)))
    allpanels = np.vstack([group_points(number) for number in panels])
    rows.append(report("panels-all", allpanels))

    # The head is the top of the body shell.  The body shell is the
    # whole character, so the head is what is left of it above the
    # shoulders, and the fit is robust for the same reason.
    head_points = np.array([
        list(vertex.co)
        for face in body_group
        for vertex in face.verts
        if vertex.co.z > 0.19
    ])
    rows.append(report("head", head_points))

    print("YXZ_SPHERES " + json.dumps(rows))

    if body_out:
        keep_faces = set(body_group)
        bmesh.ops.delete(
            bm, geom=[f for f in bm.faces if f not in keep_faces], context="FACES"
        )
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
        bm.to_mesh(body.data)
        body.data.update()
        bm.free()
        bpy.ops.export_scene.gltf(filepath=str(body_out), export_format="GLB")
        print("YXZ_BODY_ONLY %s" % body_out)


if __name__ == "__main__":
    main()
