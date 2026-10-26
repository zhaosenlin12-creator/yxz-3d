"""Which shells of the scan are floating in the air?

A piece of the toy is joined to the rest of the toy.  A scrap that came
away in the tearing is not: it hangs above the head with a gap all the
way round it, and the gap is the whole of its problem.  So the measure
is the distance from a shell to the nearest other shell.

The nearest point is found with a grid rather than by comparing every
vertex with every other, because the model has a hundred thousand
vertices and the answer is needed for every shell.

Usage:
  blender -b -P scripts/probe_yxz_floating.py -- --glb <glb> --out <json>
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


def main():
    source = value_after("--glb")
    out = value_after("--out")
    cell = float(value_after("--cell", "0.01"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)

    shell_verts = []
    for group in groups:
        shell_verts.append(np.array([[v.co.x, v.co.y, v.co.z] for f in group
                                      for v in f.verts], dtype=np.float32))
    all_points = np.concatenate(shell_verts, axis=0)
    owner = np.concatenate([np.full(len(p), i) for i, p in enumerate(shell_verts)])

    # A grid of the model's vertices, so the nearest other vertex is a
    # short walk rather than a sweep of the whole model.
    keys = np.floor(all_points / cell).astype(np.int64)
    grid = {}
    for index, key in enumerate(map(tuple, keys)):
        grid.setdefault(key, []).append(index)

    rows = []
    for number, group in enumerate(groups):
        points = shell_verts[number]
        base = np.floor(points / cell).astype(np.int64)
        gaps = np.full(len(points), np.inf, dtype=np.float32)
        for offset in range(len(points)):
            key = base[offset]
            best = np.inf
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        bucket = grid.get((key[0] + dx, key[1] + dy, key[2] + dz))
                        if not bucket:
                            continue
                        other = all_points[bucket]
                        mask = owner[bucket] != number
                        if not mask.any():
                            continue
                        distance = float(np.min(np.linalg.norm(
                            other[mask] - points[offset], axis=1)))
                        if distance < best:
                            best = distance
                            if best == 0.0:
                                break
            gaps[offset] = best
        area = float(sum(face.calc_area() for face in group))
        rows.append({
            "shell": number,
            "faces": len(group),
            "area": round(area, 7),
            "minGap": round(float(gaps.min()), 5),
            "meanGap": round(float(gaps.mean()), 5),
            "farShare": round(float((gaps > 0.004).mean()), 4),
        })

    rows.sort(key=lambda r: -r["minGap"])
    print("YXZ_FLOATING " + json.dumps({"shells": len(rows),
                                        "top": rows[:40]}))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)


main()
