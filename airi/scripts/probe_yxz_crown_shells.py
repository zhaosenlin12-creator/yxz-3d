"""What is standing above the character's head, shell by shell.

The head is clean now but there is still something standing over it,
and it is too big and too solid to be the thin sheets a sliver pass
takes.  This lists every shell with any part of itself above a given
height, with two numbers that say what it is:

`lifted`  how much of the shell is above the line, so a chip on top of
          the crown can be told from a piece that reaches down past the
          jaw.

`gap`     how far the shell is from the body.  The scan arrives welded,
          and anything that is part of the character shares its
          vertices with the body; a fragment of the old halo hanging
          over the head does not touch anything.

Usage:
  blender -b -P scripts/probe_yxz_crown_shells.py -- \
    --source <glb> [--above 0.20] [--top 40]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


# The grid the body is bucketed into when measuring the gap.  Four
# thousandths of a unit is finer than the weld the clean pass uses, so a
# part that is genuinely joined lands in the same cell or the one next
# to it.
CELL = 0.004


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


def thickness_of(group):
    """The smallest dimension of a shell, from the points it is made of."""
    points = np.array([list(face.calc_center_median()) for face in group])
    if len(points) < 3:
        return 0.0
    points = points - points.mean(axis=0)
    return float(np.linalg.svd(points, compute_uv=False)[2])


def bucket(points):
    """The body, indexed by the grid cell each of its points falls in."""
    keys = np.floor(points / CELL).astype(np.int64)
    table = {}
    for row, key in enumerate(map(tuple, keys)):
        table.setdefault(key, []).append(row)
    return table


def nearest_gap(points, table, all_points, own_rows):
    """The distance from the closest point of the shell to anything else.

    The shell's own points do not count: a shell is always as close to
    itself as it is to anything else, and the question is whether it
    touches the rest of the character.
    """
    if not len(all_points):
        return 0.0
    closest = float("inf")
    for point in points:
        base = np.floor(point / CELL).astype(np.int64)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    rows = table.get((base[0] + dx, base[1] + dy, base[2] + dz))
                    if rows:
                        near.append(rows)
        if near:
            rows = np.concatenate(near)
            rows = rows[~np.isin(rows, own_rows)]
            if not len(rows):
                continue
            block = all_points[rows]
            closest = min(closest, float(np.sqrt(((point - block) ** 2).sum(axis=1)).min()))
    # Nothing within a cell means the shell is nowhere near anything, and
    # that is a different answer from touching it.  Reported as a metre,
    # which the model is smaller than.
    return 1.0 if closest == float("inf") else closest


def main() -> None:
    source = Path(value_after("--source"))
    above = float(value_after("--above", "0.20"))
    top = int(value_after("--top", "40"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)
    body_group = max(groups, key=len)

    all_points = np.array([list(vertex.co) for vertex in bm.verts])
    table = bucket(all_points)

    rows = []
    for number, group in enumerate(groups):
        verts = [vertex for face in group for vertex in face.verts]
        if max(vertex.co.z for vertex in verts) < above:
            continue
        own = np.array(sorted({vertex.index for vertex in verts}), dtype=np.int64)
        low = [round(min(vertex.co[axis] for vertex in verts), 4) for axis in range(3)]
        high = [round(max(vertex.co[axis] for vertex in verts), 4) for axis in range(3)]
        span = (((high[0] - low[0]) * (high[1] - low[1]) * (high[2] - low[2])) ** 0.5)
        rows.append({
            "shell": number,
            "faces": len(group),
            "isBody": group is body_group,
            "lifted": f"{sum(1 for v in verts if v.co.z >= above)}/{len(verts)}",
            "gap": round(nearest_gap(
                np.array([list(vertex.co) for vertex in verts]),
                table, all_points, own), 5),
            "thick": round(thickness_of(group), 5),
            "span": round(span, 4),
            "low": low,
            "high": high,
        })
    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_CROWNSHELLS " + json.dumps({
        "above": above,
        "count": len(rows),
        "shells": rows[:top],
    }))


if __name__ == "__main__":
    main()
