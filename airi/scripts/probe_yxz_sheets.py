"""Find the torn sheets the scan left lying on the face.

The scan's own packing gives every sheet of the model its own patch of the
atlas, so a scrap that has been folded back onto the face owns a patch to
itself.  A patch that is a piece of paper -- thin in one direction, and
small -- lying on top of the face is a scrap, and a scrap is what reads
as broken.

This lists the atlas patches of a mesh, each with the size of its patch and
how thin the geometry behind it is, so the scraps can be named.

Usage:
  blender -b -P scripts/probe_yxz_sheets.py -- --glb <file> [--min-faces 40]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = Path(value_after("--glb"))
    min_faces = int(value_after("--min-faces", 40))
    max_faces = int(value_after("--max-faces", 6000))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        raise SystemExit("no uv layer")

    # An island is a set of faces joined to each other in the atlas.
    islands = []
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
                    # Two faces are neighbours in the atlas when they share
                    # an edge and their corners sit together in it.
                    others = {vert.index for vert in other.verts}
                    mine = [loop[uv_layer].uv for loop in current.loops
                            if loop.vert.index in others]
                    theirs = [loop[uv_layer].uv for loop in other.loops
                              if loop.vert.index in
                              {vert.index for vert in current.verts}]
                    if not mine or not theirs:
                        continue
                    if min((a - b).length for a in mine for b in theirs) > 0.005:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        islands.append(group)

    print("YXZ_SHEETS total=%d" % len(islands))
    rows = []
    for group in islands:
        if not (min_faces <= len(group) <= max_faces):
            continue
        points = np.array([list(vert.co) for face in group for vert in face.verts])
        centre = points.mean(axis=0)
        _, _, axes = np.linalg.svd(points - centre, full_matrices=False)
        extent = np.ptp(points @ axes.T, axis=0)
        thickness = float(min(extent))
        uvs = np.array([[loop[uv_layer].uv.x, loop[uv_layer].uv.y]
                        for face in group for loop in face.loops])
        rows.append({
            "faces": len(group),
            "centre": [round(float(v), 4) for v in centre],
            "size": [round(float(v), 4) for v in extent],
            "thickness": round(thickness, 5),
            "uvLow": [round(float(v), 4) for v in uvs.min(axis=0)],
            "uvHigh": [round(float(v), 4) for v in uvs.max(axis=0)],
        })
    rows.sort(key=lambda row: row["thickness"])
    for row in rows:
        print("YXZ_SHEET " + json.dumps(row))
    bm.free()


if __name__ == "__main__":
    main()
