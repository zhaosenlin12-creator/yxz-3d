"""The islands of the head, and which of them stand proud of the helmet.

The crown of the helmet is built from a handful of big tiles that tile the
dome between them.  The scan also left a few thin sheets lying on top of
that dome, and they are what the character reads as broken: a torn flap
sticking up out of the top of the head, a strip of glass lying across the
crown.

The tiles and the sheets are told apart by their own shape.  A tile is a
piece of the dome: it is thick enough to have a skin and a back, and it
follows the surface the dome is built on.  A sheet is a skin without a back,
it is thin, and it stands off the dome by more than a millimetre or two.

So this lists every island of the head with the two numbers that decide
it: how thin it is, and how far off the dome it stands.

Usage:
  blender -b -P scripts/probe_yxz_crown_debris.py -- \
    --source <glb> [--centre 0.038,-0.001,0.094] [--min-z 0.18]
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


def islands(bm):
    """Every connected group of faces, keyed by the index of its first face."""
    bm.faces.ensure_lookup_table()
    unvisited = set(bm.faces)
    groups = []
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


def spread(points):
    """How far the points spread across their own best-fit plane."""
    if len(points) < 3:
        return 0.0
    mean = Vector((sum(p.x for p in points) / len(points),
                   sum(p.y for p in points) / len(points),
                   sum(p.z for p in points) / len(points)))
    covariance = [[0.0] * 3 for _ in range(3)]
    for point in points:
        d = point - mean
        for i in range(3):
            for j in range(3):
                covariance[i][j] += d[i] * d[j]
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
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    min_z = float(value_after("--min-z", "0.18"))
    max_radius = float(value_after("--max-radius", "0.42"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    rows = []
    for number, group in enumerate(islands(bm)):
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            continue
        middle = Vector((sum(p.x for p in points) / len(points),
                         sum(p.y for p in points) / len(points),
                         sum(p.z for p in points) / len(points)))
        radii = [(p - centre).length for p in points]
        elevations = [math.degrees(math.asin(max(-1.0, min(1.0, (p - centre).z
                                                            / max(1e-6, (p - centre).length)))))
                       for p in points]
        if middle.z < min_z:
            continue
        if sum(radii) / len(radii) > max_radius:
            continue
        rows.append({
            "island": number,
            "faces": len(group),
            "centre": [round(v, 4) for v in middle],
            "z": round(middle.z, 4),
            "elev": round(sum(elevations) / len(elevations), 1),
            "rMin": round(min(radii), 4),
            "rMax": round(max(radii), 4),
            "thick": round(spread(points), 4),
            "box": [round(min(p.x for p in points), 3), round(min(p.y for p in points), 3),
                    round(min(p.z for p in points), 3), round(max(p.x for p in points), 3),
                    round(max(p.y for p in points), 3), round(max(p.z for p in points), 3)],
        })

    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_CROWN_DEBRIS " + json.dumps(rows))
    bm.free()


if __name__ == "__main__":
    main()
