"""The pieces the head is made of, and which of them are the glass.

The scan of the head carries two things: the white helmet, which is a
wide flattened dome, and a clear bubble that stands over it.  The
bubble is what the scan shattered, and the pieces of it are what make
the head read as broken glass.  The helmet itself is mostly whole, so
the pieces have to be told apart from it rather than the head being
rebuilt.

Two things tell them apart.  The bubble stands clear of the helmet, so
it sits outside the surface the helmet is built on.  And the bubble is
a thin skin, so the big pieces of it are nearly flat sheets, while the
helmet is a dome.

This lists the pieces with both numbers, so the glass can be picked
out of them.

Usage:
  blender -b -P scripts/probe_yxz_crown_shells2.py -- \
    --source <glb> [--min-faces 20] [--top 50]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
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


def thickness(points):
    """How far the points spread across their own best-fit plane."""
    if len(points) < 3:
        return 0.0
    mean = Vector((sum(p.x for p in points) / len(points),
                   sum(p.y for p in points) / len(points),
                   sum(p.z for p in points) / len(points)))
    # The smallest principal axis is the plane; the spread along it is
    # how flat the piece is.
    covariance = [[0.0] * 3 for _ in range(3)]
    for point in points:
        d = point - mean
        for i in range(3):
            for j in range(3):
                covariance[i][j] += d[i] * d[j]
    # Three rounds of deflation on the largest axis, which is enough for
    # a piece that is either a sheet or a dome.
    axes = []
    remaining = list(range(3))
    for _ in range(3):
        best = None
        for index in remaining:
            value = covariance[index][index]
            if best is None or value < best[0]:
                best = (value, index)
        remaining.remove(best[1])
        axes.append(best[0])
    return math.sqrt(max(0.0, min(axes))) * 2.0


def main() -> None:
    source = Path(value_after("--source"))
    min_faces = int(value_after("--min-faces", "20"))
    top = int(value_after("--top", "50"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    radii = [float(v) for v in
              value_after("--radii", "0.30,0.31,0.28").split(",")]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    def in_head(point):
        if (point - centre).length > 0.40:
            return False
        return point.z >= centre.z - 0.22

    def surface_ratio(point):
        value = 0.0
        for axis in range(3):
            value += ((point[axis] - centre[axis]) / radii[axis]) ** 2
        return math.sqrt(value)

    rows = []
    for number, group in enumerate(shells(bm)):
        if len(group) < min_faces:
            continue
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            continue
        centre_point = Vector((sum(p.x for p in points) / len(points),
                               sum(p.y for p in points) / len(points),
                               sum(p.z for p in points) / len(points)))
        if not in_head(centre_point):
            continue
        ratios = [surface_ratio(p) for p in points]
        rows.append({
            "shell": number,
            "faces": len(group),
            "centre": [round(v, 3) for v in centre_point],
            "z": round(centre_point.z, 3),
            "flat": round(thickness(points), 4),
            "sMin": round(min(ratios), 3),
            "sMax": round(max(ratios), 3),
            "sMean": round(sum(ratios) / len(ratios), 3),
        })

    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_CROWN_PIECES " + json.dumps(rows[:top]))
    print("YXZ_CROWN_TOTAL " + json.dumps({
        "pieces": len(rows),
        "faces": sum(row["faces"] for row in rows),
        "flatSheets": sum(1 for row in rows if row["flat"] < 0.012 and row["faces"] > 300),
    }))
    bm.free()


if __name__ == "__main__":
    main()
