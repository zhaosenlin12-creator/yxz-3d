"""List the shells around the head, biggest first.

The head is a white helmet with a glass bubble over it, and the scan
shattered both.  Which of the pieces is which cannot be told from the
outside: a bubble fragment and a helmet fragment are both white and both
are torn.  It can be told from the inside, by how far the piece sits
from the sphere the helmet is built on.  The helmet's panels lie on a
sphere of one radius; the bubble lies on a larger one, clear of the
helmet all the way round.

Usage:
  blender -b -P scripts/probe_yxz_head_shells.py -- \
    --source <glb> [--min-faces 40] [--top 60]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh


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


def main() -> None:
    source = Path(value_after("--source"))
    min_faces = int(value_after("--min-faces", "40"))
    top = int(value_after("--top", "60"))
    centre = [float(v) for v in value_after("--centre", "0.038,-0.001,0.094").split(",")]
    radius = float(value_after("--radius", "0.289"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)

    rows = []
    for number, group in enumerate(groups):
        if len(group) < min_faces:
            continue
        points = [v.co for face in group for v in face.verts]
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        distances = [
            math.sqrt(
                (p[0] - centre[0]) ** 2
                + (p[1] - centre[1]) ** 2
                + (p[2] - centre[2]) ** 2
            )
            for p in points
        ]
        rows.append({
            "shell": number,
            "faces": len(group),
            "low": [round(v, 4) for v in low],
            "high": [round(v, 4) for v in high],
            "rMin": round(min(distances), 4),
            "rMax": round(max(distances), 4),
            "rMean": round(sum(distances) / len(distances), 4),
            "offSphere": round(sum(abs(d - radius) for d in distances) / len(distances), 4),
        })

    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_HEAD_SHELLS " + json.dumps(rows[:top]))
    bm.free()


if __name__ == "__main__":
    main()
