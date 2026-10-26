"""Which faces of the body make up the fin standing off the crown.

The wreck of the old halo is welded into the body, so it cannot be
taken off as a piece -- it has to be taken off as faces.  This lists
the faces of the body above a height, grouped by the rectangle of the
atlas they are painted with, so the ones that belong to the wreck can
be told from the helmet's own by the patch of texture they wear.

Usage:
  blender -b -P scripts/probe_yxz_crown_faces.py -- \
    --source <glb> [--above 0.28] [--top 20]
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


def load_atlas():
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


def main() -> None:
    source = Path(value_after("--source"))
    above = float(value_after("--above", "0.28"))
    top = int(value_after("--top", "20"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    atlas = load_atlas()

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active

    islands = {}
    for face in bm.faces:
        if max(vertex.co.z for vertex in face.verts) < above:
            continue
        us = [loop[uv_layer].uv.x for loop in face.loops]
        vs = [loop[uv_layer].uv.y for loop in face.loops]
        # Faces are bucketed by a grid of the atlas rather than by
        # their own rectangle, because a face's rectangle is the shape
        # of a triangle and the same island arrives as many of them.
        key = (round(min(us) * 40) / 40, round(min(vs) * 40) / 40)
        entry = islands.setdefault(key, {"faces": 0, "us": [], "vs": [], "colours": []})
        entry["faces"] += 1
        entry["us"].extend(us)
        entry["vs"].extend(vs)
        if atlas is not None:
            u = sum(us) / len(us)
            v = sum(vs) / len(vs)
            x = int(min(max(u, 0.0), 1.0) * (atlas.shape[1] - 1))
            y = int(min(max(v, 0.0), 1.0) * (atlas.shape[0] - 1))
            entry["colours"].append([round(float(c), 3) for c in atlas[y, x][:3]])

    rows = []
    for key, entry in islands.items():
        colours = entry["colours"]
        mean = [round(sum(c[i] for c in colours) / len(colours), 3) for i in range(3)] if colours else []
        rows.append({
            "at": [round(key[0], 3), round(key[1], 3)],
            "faces": entry["faces"],
            "rect": [
                round(min(entry["us"]), 4), round(min(entry["vs"]), 4),
                round(max(entry["us"]), 4), round(max(entry["vs"]), 4),
            ],
            "meanColour": mean,
        })
    rows.sort(key=lambda row: row["faces"], reverse=True)
    print("YXZ_CROWNFACES " + json.dumps({
        "above": above,
        "islands": len(rows),
        "top": rows[:top],
    }))


if __name__ == "__main__":
    main()
