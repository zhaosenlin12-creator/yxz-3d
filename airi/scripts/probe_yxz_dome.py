"""Measure the helmet: the bubble's sphere, and the head's.

The scan gave the character's bubble helmet back as several large
panels and a drift of fragments, so the panels and the fragments are
parts of one surface and the surface is a sphere.  Fitting that sphere
to the panels gives the bubble back, exactly, and the only thing that
is missing is the part of it that was shattered.

The head is measured the same way, so the bubble can be placed around
it rather than guessed at.

Usage:
  blender -b -P scripts/probe_yxz_dome.py -- --glb <glb>
    [--panels 3178,3150,3252,3487] [--head-z 0.24]
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
    distance = np.linalg.norm(points - centre, axis=1)
    return centre, radius, float(distance.std()), float(distance.max())


def main() -> None:
    glb = Path(value_after("--glb"))
    panels = [
        int(piece)
        for piece in value_after("--panels", "3178,3150,3252,3487").split(",")
        if piece.strip()
    ]
    head_z = float(value_after("--head-z", "0.24"))

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

    panel_points = []
    for number in panels:
        group = groups[number]
        panel_points.extend(
            [list(vertex.co) for face in group for vertex in face.verts]
        )
    panel_points = np.array(panel_points)

    head_points = np.array([
        list(vertex.co)
        for face in body_group
        for vertex in face.verts
        if vertex.co.z > head_z
    ])

    def describe(name, points):
        centre, radius, deviation, worst = fit_sphere(points)
        return {
            "name": name,
            "count": int(len(points)),
            "centre": [round(float(value), 4) for value in centre],
            "radius": round(radius, 4),
            "deviation": round(deviation, 4),
            "worst": round(worst, 4),
            "low": [round(float(points[:, axis].min()), 4) for axis in range(3)],
            "high": [round(float(points[:, axis].max()), 4) for axis in range(3)],
        }

    print("YXZ_DOME " + json.dumps({
        "panels": describe("panels", panel_points),
        "head": describe("head", head_points),
    }))
    bm.free()


if __name__ == "__main__":
    main()
