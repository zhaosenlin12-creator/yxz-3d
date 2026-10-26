"""Fit the shape of the helmet, so the glass on it can be taken off.

The head was being treated as a sphere, and it is not one.  The helmet
is a wide, flattened dome: from the top it is an oval, not a circle,
and its crown is broader than a sphere of the same height.  Fitting a
sphere to it and calling everything outside the sphere "bubble" took
the helmet's own crown off with it, which is how the head ended up
flat-topped and the crown had to be rebuilt from nothing.

So the helmet is fitted as an ellipsoid -- wide, flat, and axis
aligned, which is how it was modelled -- and the pieces that stand
clear of that are the glass.  A piece that is also flat is a sheet of
the bubble rather than a piece of the helmet, because the helmet is a
dome and a dome is not flat.

Usage:
  blender -b -P scripts/fit_yxz_crown.py -- --source <glb> [--report-only]
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


def planarity(points):
    """The spread of the points across their own best-fit plane."""
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=float)
    if len(array) < 3:
        return 0.0, 0.0
    centred = array - array.mean(axis=0)
    values, vectors = np.linalg.eigh(centred.T @ centred)
    residual = math.sqrt(max(0.0, values[0]) / len(array))
    normal = vectors[:, 0]
    return residual, abs(float(normal @ np.array([0.0, 0.0, 1.0])))


def fit_ellipsoid(points, centre, initial):
    """A weighted fit of an axis-aligned ellipsoid to the outer surface."""
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=float)
    origin = np.array(centre, dtype=float)
    abc = np.array(initial, dtype=float)
    weights = np.ones(len(array))
    scale = 1.0
    for _ in range(24):
        relative = array - origin
        a2, b2, c2 = abc * abc
        value = ((relative[:, 0] / a2) ** 2 + (relative[:, 1] / b2) ** 2
                 + (relative[:, 2] / c2) ** 2)
        scale = math.sqrt(max(1e-9, float(np.median(value))))
        distance = np.abs(np.sqrt(value) - scale)
        # The surface is the largest population of points at one radius,
        # so the fit is pulled towards the mode and the rest is let go.
        weights = np.exp(-((distance / 0.045) ** 2))
        if weights.sum() < 32:
            break
        design = np.stack([
            weights * relative[:, 0] ** 2,
            weights * relative[:, 1] ** 2,
            weights * relative[:, 2] ** 2,
        ], axis=1)
        target = weights * scale ** 2
        solution, *_ = np.linalg.lstsq(design, target, rcond=None)
        abc = np.array([1.0 / math.sqrt(max(1e-9, s)) for s in solution])
    return abc, origin, weights


def main() -> None:
    source = Path(value_after("--source"))
    centre = [float(v) for v in
              value_after("--centre", "0.038,-0.001,0.094").split(",")]
    initial = [float(v) for v in
               value_after("--initial", "0.30,0.31,0.28").split(",")]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    origin = Vector(centre)

    def in_head(point):
        if (point - origin).length > 0.42:
            return False
        return point.z >= origin.z - 0.24

    candidate_faces = [face for face in bm.faces if in_head(face.calc_center_median())]
    candidate_verts = {v for face in candidate_faces for v in face.verts}

    abc, fitted_centre, weights = fit_ellipsoid(
        [v.co.copy() for v in candidate_verts], centre, initial)

    def ratio(point):
        relative = point - Vector(fitted_centre)
        value = ((relative.x / abc[0]) ** 2 + (relative.y / abc[1]) ** 2
                 + (relative.z / abc[2]) ** 2)
        return math.sqrt(value)

    pieces = []
    for number, group in enumerate(shells(bm)):
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            continue
        middle = Vector((sum(p.x for p in points) / len(points),
                         sum(p.y for p in points) / len(points),
                         sum(p.z for p in points) / len(points)))
        if not in_head(middle):
            continue
        ratios = [ratio(p) for p in points]
        residual, upright = planarity(points)
        pieces.append({
            "shell": number,
            "faces": len(group),
            "centre": [round(v, 3) for v in middle],
            "flat": round(residual, 4),
            "upright": round(upright, 3),
            "sMean": round(sum(ratios) / len(ratios), 3),
            "sMax": round(max(ratios), 3),
        })

    pieces.sort(key=lambda piece: piece["faces"], reverse=True)
    print("YXZ_FIT " + json.dumps({
        "radii": [round(v, 4) for v in abc],
        "centre": [round(v, 4) for v in fitted_centre],
        "inliers": int(weights.sum()),
    }))
    print("YXZ_FIT_PIECES " + json.dumps(pieces[:36]))
    bm.free()


if __name__ == "__main__":
    main()
