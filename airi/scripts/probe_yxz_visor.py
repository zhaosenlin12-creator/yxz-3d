"""Where the visor is, and where the bubble's rim has to run.

The bubble is going to be rebuilt as a clean sphere, and it has to
have a hole in it for the face.  The hole is bounded by the visor,
so the visor is measured: which faces carry the dark blue of the
screen, and where they are.

The colour is read out of the model's own atlas rather than guessed
at, and the faces that use it are found by the texel in the middle
of each face, which is enough to pick the visor out of the rest.

Usage:
  blender -b -P scripts/probe_yxz_visor.py -- --glb <glb>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
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
    raise RuntimeError("no base colour image in the file")


def main() -> None:
    glb = Path(value_after("--glb"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    atlas = load_atlas()
    height, width = atlas.shape[0], atlas.shape[1]
    uv_layer = body.data.uv_layers.active

    # The screen of the visor is a deep blue: blue much stronger than
    # red, and dark enough that it is not the white of the shell.
    samples = []
    for polygon in body.data.polygons:
        if len(polygon.loop_indices) == 0:
            continue
        u = 0.0
        v = 0.0
        for index in polygon.loop_indices:
            u += uv_layer.data[index].uv.x
            v += uv_layer.data[index].uv.y
        u /= len(polygon.loop_indices)
        v /= len(polygon.loop_indices)
        x = int(min(max(u, 0.0), 1.0) * (width - 1))
        y = int(min(max(v, 0.0), 1.0) * (height - 1))
        pixel = atlas[y, x]
        r = float(pixel[0])
        g = float(pixel[1])
        b = float(pixel[2])
        if b > 0.02 and b > r * 1.8 and b > g * 1.4 and b < 0.25:
            samples.append(polygon)
    if not samples:
        print("YXZ_VISOR " + json.dumps({"found": 0}))
        return
    low = [0.0, 0.0, 0.0]
    high = [0.0, 0.0, 0.0]
    counts = {}
    for polygon in samples:
        points = [body.data.vertices[index].co for index in polygon.vertices]
        for axis in range(3):
            low[axis] = min(low[axis], min(point[axis] for point in points))
            high[axis] = max(high[axis], max(point[axis] for point in points))
        middle = sum(point.z for point in points) / len(points)
        key = round(middle, 2)
        counts[key] = counts.get(key, 0) + 1
    print("YXZ_VISOR " + json.dumps({
        "found": len(samples),
        "low": [round(value, 4) for value in low],
        "high": [round(value, 4) for value in high],
        "zHistogram": dict(sorted(counts.items())),
    }))


if __name__ == "__main__":
    main()
