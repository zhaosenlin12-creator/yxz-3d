"""Census of the scan's own pieces, straight from the source file.

The scan arrives as a couple of hundred disconnected shells, and the ones
that are not the character -- the remains of the halo, mostly -- float
above the head where they are the most obvious thing about the model.
This lists every shell with its bounds, so the floating ones can be
named by the rule that removes them and no more.

Usage:
  blender -b -P scripts/probe_yxz_pieces.py -- --glb <file> [--min-z 0.3]
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


def components(bm):
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
    return groups


def main() -> None:
    glb = Path(value_after("--glb"))
    min_z = float(value_after("--min-z", 0.3))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = components(bm)
    print("YXZ_PIECES total=%d" % len(groups))
    for group in groups:
        cloud = np.array([list(face.calc_center_median()) for face in group])
        high = float(cloud[:, 2].max())
        if high < min_z:
            continue
        print("YXZ_PIECE " + json.dumps({
            "faces": len(group),
            "centre": [round(float(v), 4) for v in cloud.mean(axis=0)],
            "low": [round(float(v), 4) for v in cloud.min(axis=0)],
            "high": [round(float(v), 4) for v in cloud.max(axis=0)],
        }))
    bm.free()


if __name__ == "__main__":
    main()
