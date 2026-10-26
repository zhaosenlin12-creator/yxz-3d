"""Count the flat flakes lying on the shell, all over the figure.

The scan is stitched from a great many separate pieces, and between the
big panels there is a scatter of much smaller ones: single triangles and
two-triangle chips lying flat on the surface of the character, each one
its own island, none of them joined to anything.

They are invisible as shape -- they have no silhouette of their own --
but they are not invisible as pixels.  A chip that lies flat on a white
shell is either wound the wrong way round, in which case it is shaded as
the dark inner face, or it is so close to the panel it lies on that the
depth test cannot decide which of the two is in front, in which case it
speckles.  Either way the white shell comes out of the render covered in
black flecks, and a character covered in black flecks reads as a
shattered scan rather than as a figure in a suit of armour.

This counts them so the number can be seen before anything is removed.
The test is the shape of the island: a chip that lies flat on a surface
is a skin without a back, so its own points are nearly coplanar, while
anything with a shape of its own -- an ear cup, a star, a boot -- is not.

Usage:
  blender -b -P scripts/probe_yxz_shell_debris.py -- --source <glb> \
    [--thin 0.010] [--max-faces 150]
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


def islands(bm):
    """Every connected group of faces, in the order the mesh keeps them."""
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


def flatness(points):
    """How far the points spread across their own best-fit plane."""
    if len(points) < 3:
        return 0.0
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
    array -= array.mean(axis=0)
    singular = np.linalg.svd(array, compute_uv=False)
    return float(singular[2]) * 2.0


def main() -> None:
    source = Path(value_after("--source"))
    thin = float(value_after("--thin", "0.010"))
    max_faces = int(value_after("--max-faces", "150"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    groups = islands(bm)
    body_group = max(groups, key=len)
    body_points = np.array([
        [v.co.x, v.co.y, v.co.z] for face in body_group for v in face.verts
    ])
    body_keys = np.floor(body_points / 0.01).astype(np.int64)
    table = {}
    for row, key in enumerate(map(tuple, body_keys)):
        table.setdefault(key, []).append(row)

    candidates = []
    for number, group in enumerate(groups):
        if group is body_group:
            continue
        if len(group) > max_faces:
            continue
        points = [v.co.copy() for face in group for v in face.verts]
        if len(points) < 3:
            continue
        flat = flatness(points)
        if flat > thin:
            continue
        array = np.array([[p.x, p.y, p.z] for p in points])
        # How far the chip stands off the body it lies on.  A chip that
        # is welded to the panel underneath is at zero distance; a piece
        # of the design that happens to be flat stands off it.
        keys = np.floor(array / 0.01).astype(np.int64)
        near = []
        for key in map(tuple, keys):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        rows = table.get((key[0] + dx, key[1] + dy, key[2] + dz))
                        if rows:
                            near.append(body_points[rows])
        gap = None
        if near:
            block = np.concatenate(near)
            for point in array:
                distance = float(np.sqrt(((point - block) ** 2).sum(axis=1)).min())
                gap = distance if gap is None else min(gap, distance)
                break
        candidates.append({
            "island": number,
            "faces": len(group),
            "flat": round(flat, 5),
            "gap": None if gap is None else round(gap, 5),
            "z": round(sum(p.z for p in points) / len(points), 4),
        })

    candidates.sort(key=lambda row: row["faces"], reverse=True)
    total_faces = sum(row["faces"] for row in candidates)
    welded = [row for row in candidates
              if row["gap"] is not None and row["gap"] < 0.004]
    print("YXZ_SHELL_DEBRIS " + json.dumps({
        "islands": len(groups),
        "candidates": len(candidates),
        "candidateFaces": total_faces,
        "weldedToBody": len(welded),
        "weldedFaces": sum(row["faces"] for row in welded),
        "largest": candidates[:20],
    }))
    bm.free()


if __name__ == "__main__":
    main()
