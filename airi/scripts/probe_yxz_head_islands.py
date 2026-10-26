"""Every piece of the head, with the numbers that tell them apart.

The head is made of a dome of white shell with a few pieces of design
standing proud of it -- the bezel round the visor, the star on the
forehead, the hair -- and, on top of that, the litter of the scan: the
clear bubble that stood over the helmet and shattered, the strips of
shell that were torn off and never taken away, and the copies of the
surface that lie a fraction of a millimetre off it.

The numbers that tell the two apart are how far out from the middle of
the head each piece stands, and how thick it is.  A piece of the design
stands proud and has body; a piece of litter stands proud and is paper.

Usage:
  blender -b -P scripts/probe_yxz_head_islands.py -- \
    --glb <glb> --out <json> [--centre 0.038,-0.001,0.094] [--radius 0.36]
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


def islands(bm):
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


def thickness(points):
    """How far the points spread across their own best-fit plane."""
    if len(points) < 3:
        return 0.0
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
    array -= array.mean(axis=0)
    singular = np.linalg.svd(array, compute_uv=False)
    return float(singular[2]) * 2.0


def main() -> None:
    glb = Path(value_after("--glb"))
    out = Path(value_after("--out"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    limit = float(value_after("--radius", "0.36"))
    high = float(value_after("--high", "0.2925"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    rows = []
    for number, group in enumerate(islands(bm)):
        middles = [face.calc_center_median() for face in group]
        radii = [(m - centre).length for m in middles]
        near = [(m, r) for m, r in zip(middles, radii) if r < limit]
        if not near:
            continue
        points = [face.calc_center_median() for face in group]
        average = Vector((sum(p.x for p in points) / len(points),
                          sum(p.y for p in points) / len(points),
                          sum(p.z for p in points) / len(points)))
        rows.append({
            "island": number,
            "faces": len(group),
            "nearFaces": len(near),
            "rMin": round(min(radii), 4),
            "rMax": round(max(radii), 4),
            "rNearMin": round(min(r for _, r in near), 4),
            "rNearMax": round(max(r for _, r in near), 4),
            "aboveHigh": sum(1 for _, r in near if r > high),
            "thick": round(thickness(points), 4),
            "at": [round(v, 4) for v in average],
            "zMin": round(min(m.z for m, _ in near), 4),
            "zMax": round(max(m.z for m, _ in near), 4),
            "xMin": round(min(m.x for m, _ in near), 4),
            "xMax": round(max(m.x for m, _ in near), 4),
        })

    rows.sort(key=lambda row: -row["nearFaces"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "glb": str(glb),
        "headCentre": list(centre),
        "high": high,
        "islands": len(rows),
        "rows": rows,
    }, indent=1), encoding="utf-8")
    print("YXZ_ISLANDS %s rows=%d" % (out, len(rows)))
    bm.free()


if __name__ == "__main__":
    main()
