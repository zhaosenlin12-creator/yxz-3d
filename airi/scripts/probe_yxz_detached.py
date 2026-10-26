"""Which shells of the scan are floating in the air?

A piece of the toy is joined to the rest of the toy.  A scrap that came
away in the tearing is not: it hangs in the space above the head with a
gap all the way round it.  The gap is what makes it a scrap, so the
distance from a shell to the nearest other shell is the measure.

Usage:
  blender -b -P scripts/probe_yxz_detached.py -- --glb <glb> --out <json>
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
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)

    # The vertices of every shell, and the vertices of the model as a whole.
    shell_verts = []
    for group in groups:
        points = np.array([[v.co.x, v.co.y, v.co.z] for f in group
                           for v in f.verts])
        shell_verts.append(points)
    all_points = np.concatenate(shell_verts, axis=0)
    owner = np.concatenate([np.full(len(p), i) for i, p in enumerate(shell_verts)])

    rows = []
    for number, group in enumerate(groups):
        points = shell_verts[number]
        others = owner != number
        gap = float(np.min(np.linalg.norm(
            all_points[others][:, None, :] - points[None, :, :], axis=2))) \
            if len(points) * others.sum() < 4e7 else None
        if gap is None:
            # too big to do in one bite: sample the shell instead
            sample = points[::max(1, len(points) // 400)]
            gap = float(np.min(np.linalg.norm(
                all_points[others][:, None, :] - sample[None, :, :], axis=2)))
        area = float(sum(f.calc_area() for f in group))
        rows.append({"shell": number, "faces": len(group),
                     "area": round(area, 7), "gap": round(gap, 5)})

    rows.sort(key=lambda r: -r["gap"])
    print("YXZ_DETACHED " + json.dumps({
        "shells": len(rows),
        "top": rows[:40],
    }))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)


main()
