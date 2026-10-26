"""Which faces are smearing the atlas across themselves?

A triangle whose three corners carry places in the atlas that are a long
way apart does not show three colours: it shows a gradient from one to
the other, straight across the picture, whatever the picture has in the
middle.  On a navy face that is a white smear, and it is what the visor
is covered in.

The test is the ratio of the area the triangle covers in the atlas to
the area it covers on the model.  For a triangle that is unwrapped
correctly the ratio is the same for every triangle of the model, so a
triangle whose ratio is far from the rest is one whose corners have
been pulled to different parts of the picture.

Usage:
  blender -b -P scripts/probe_yxz_uv_smear.py -- \
    --source <glb> [--top 30] [--ratio 20]
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


def sample(atlas, uv):
    x = int(min(max(uv.x, 0.0), 1.0) * (atlas.shape[1] - 1))
    y = int(min(max(uv.y, 0.0), 1.0) * (atlas.shape[0] - 1))
    return [round(float(c), 3) for c in atlas[y, x][:3]]


def triangle_area_uv(uv):
    return abs((uv[1].x - uv[0].x) * (uv[2].y - uv[0].y)
               - (uv[2].x - uv[0].x) * (uv[1].y - uv[0].y)) * 0.5


def main() -> None:
    source = Path(value_after("--source"))
    top = int(value_after("--top", "30"))
    ratio_limit = float(value_after("--ratio", "20"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    atlas = load_atlas()

    rows = []
    ratios = []
    for face in bm.faces:
        if len(face.loops) != 3:
            continue
        uv = [loop[uv_layer].uv for loop in face.loops]
        uv_area = triangle_area_uv(uv)
        area = face.calc_area()
        if area < 1e-9 or uv_area < 1e-12:
            continue
        ratio = uv_area / area
        ratios.append(ratio)
        rows.append((ratio, face.calc_center_median(), uv,
                     [sample(atlas, item) for item in uv],
                     round(area, 8)))

    median = float(np.median(ratios))
    smears = [row for row in rows if row[0] > median * ratio_limit]
    smears.sort(key=lambda row: -row[0])

    print("YXZ_UV_SMEAR " + json.dumps({
        "faces": len(rows),
        "medianRatio": round(median, 4),
        "limit": round(median * ratio_limit, 4),
        "smearFaces": len(smears),
        "smearArea": round(sum(row[4] for row in smears), 6),
        "totalArea": round(sum(row[4] for row in rows), 6),
    }))
    for ratio, centre, uv, colours, area in smears[:top]:
        print("YXZ_UV_ROW " + json.dumps({
            "ratio": round(ratio / median, 1),
            "at": [round(float(c), 3) for c in centre],
            "uv": [[round(v.x, 4), round(v.y, 4)] for v in uv],
            "colours": colours,
            "area": area,
        }))
    bm.free()


if __name__ == "__main__":
    main()
