"""Where does the visor panel live in the atlas?

The visor is one dark blue panel across the front of the head, but it
is not a shell of its own -- it is part of the body's single sheet, so
its place in the texture is scattered over whatever rectangles the
packing gave that part of the sheet.  That makes it impossible to crop
the visor out of the atlas, and the two bright marks on the panel --
the jagged crack and the bar of light -- cannot be found in the
picture without knowing where the panel is.

So the panel is found by the two things that make it the panel: the
faces are at the front of the head, and the atlas says they are the
dark blue of the visor.  Every face that is both is marked, and the
marks are drawn over a copy of the atlas so the result can be looked
at rather than trusted.

Usage:
  blender -b -P scripts/probe_yxz_visor_patch.py -- --glb <glb> --out <png>
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


def main() -> None:
    source = value_after("--glb")
    out = value_after("--out")
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
    if colour is None:
        print("YXZ_VISOR_PATCH no colour atlas")
        return
    width, height = colour.size
    pixels = np.array(colour.pixels[:], dtype=np.float32).reshape(height, width, 4)
    pixels = pixels[::-1]  # Blender reads images bottom up; pictures are top down

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    mask = np.zeros((height, width), dtype=bool)
    samples = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if not (centre.y < -0.10 and -0.30 < centre.z < 0.32):
            continue
        us = [loop[uv_layer].uv.x for loop in face.loops]
        vs = [loop[uv_layer].uv.y for loop in face.loops]
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        x = min(width - 1, max(0, int(u * width)))
        y = min(height - 1, max(0, int((1.0 - v) * height)))
        r, g, b = pixels[y, x, :3]
        samples.append([float(r), float(g), float(b)])
        # The visor's own colour: dark, and clearly blue.
        if b > r + 0.06 and b > 0.12 and r < 0.55 and g < 0.65:
            mask[max(0, y - 6):y + 7, max(0, x - 6):x + 7] = True

    if out:
        rgba = pixels.copy()
        rgba[mask, 0] = 1.0
        rgba[mask, 1] = 0.0
        rgba[mask, 2] = 0.0
        rgba[mask, 3] = 1.0
        image = bpy.data.images.new("mask", width=width, height=height)
        image.pixels = rgba[::-1].ravel().tolist()
        image.filepath_raw = str(out)
        image.file_format = "PNG"
        image.save()
        print("YXZ_VISOR_MASK " + str(out))

    if samples:
        array = np.array(samples)
        print("YXZ_VISOR_PATCH " + json.dumps({
            "faces": len(samples),
            "meanColour": [round(float(v), 4) for v in array.mean(axis=0)],
            "maskPixels": int(mask.sum()),
        }))
    bm.free()


main()
