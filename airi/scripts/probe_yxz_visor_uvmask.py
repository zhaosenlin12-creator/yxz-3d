"""Draw the visor's own place in the texture.

The visor is the dark blue panel across the front of the head, and the
scan painted white on it: a jagged crack and a bar of light.  Both are
in the texture rather than in the shape, so they can only be found
where the panel is, and the panel is not a piece of the model that can
be cropped out of the texture -- it is part of the body's one sheet,
scattered over whatever rectangles the packing gave it.

So the panel is traced.  Every face of the body that is at the front
of the head and is the dark blue of the visor is drawn, in texture
space, into a picture the size of the atlas.  What comes out is the
visor's exact footprint, and any white inside that footprint is paint
that was laid on top of the panel.

Usage:
  blender -b -P scripts/probe_yxz_visor_uvmask.py -- \
    --glb <glb> --out <png>
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def triangle(mask, width, height, a, b, c):
    """Fill the triangle a-b-c into a texture space mask."""
    min_x = max(0, int(min(a[0], b[0], c[0])))
    max_x = min(width - 1, int(max(a[0], b[0], c[0])))
    min_y = max(0, int(min(a[1], b[1], c[1])))
    max_y = min(height - 1, int(max(a[1], b[1], c[1])))
    if min_x > max_x or min_y > max_y:
        return
    ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
    px = xs + 0.5
    py = ys + 0.5
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-9:
        return
    w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
    w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -0.002) & (w1 >= -0.002) & (w2 >= -0.002)
    mask[min_y:max_y + 1, min_x:max_x + 1] |= inside


def main() -> None:
    source = value_after("--glb")
    out = Path(value_after("--out"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    colour = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            colour = image
            break
    width, height = colour.size
    pixels = np.array(colour.pixels[:], dtype=np.float32).reshape(height, width, 4)[::-1]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    mask = np.zeros((height, width), dtype=bool)
    traced = 0
    for face in bm.faces:
        centre = face.calc_center_median()
        if centre.z < 0.02:
            continue
        us = [loop[uv_layer].uv.x for loop in face.loops]
        vs = [loop[uv_layer].uv.y for loop in face.loops]
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        x = min(width - 1, max(0, int(u * width)))
        y = min(height - 1, max(0, int((1.0 - v) * height)))
        r, g, b = pixels[y, x, :3]
        if not (b > r + 0.10 and b < 0.72 and r < 0.42):
            continue
        traced += 1
        points = [
            (loop[uv_layer].uv.x * width, (1.0 - loop[uv_layer].uv.y) * height)
            for loop in face.loops
        ]
        for index in range(1, len(points) - 1):
            triangle(mask, width, height, points[0], points[index], points[index + 1])

    image = bpy.data.images.new("visor", width=width, height=height)
    buffer = np.zeros((height, width, 4), dtype=np.float32)
    buffer[:, :, 3] = 1.0
    buffer[mask, 0] = 1.0
    image.pixels = buffer[::-1].ravel().tolist()
    image.filepath_raw = str(out)
    image.file_format = "PNG"
    image.save()
    print("YXZ_VISOR_UVMASK " + str(out) + " faces " + str(traced)
          + " texels " + str(int(mask.sum())))
    bm.free()


main()
