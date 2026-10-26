"""Where the star on the forehead is.

The star is a raised emblem on the front of the helmet, and it is
blue where the helmet is white.  It has to be found by its colour,
because the crown it sits on is being taken off and replaced, and the
star has to survive that.

Usage:
  blender -b -P scripts/probe_yxz_star.py -- --source <glb>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = Path(value_after("--source"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    material = body.data.materials[0]
    pixels, width, height = None, 0, 0
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            image = node.image
            width, height = image.size
            pixels = [0.0] * (width * height * 4)
            image.pixels.foreach_get(pixels)
            break

    blue = []
    for face in bm.faces:
        middle = face.calc_center_median()
        if (middle - centre).length > 0.42:
            continue
        if middle.z < centre.z + 0.16:
            continue
        if middle.x < centre.x + 0.17:
            continue
        if pixels is None:
            break
        total = [0.0, 0.0, 0.0]
        count = 0
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = min(width - 1, max(0, int(uv.x * width)))
            y = min(height - 1, max(0, int(uv.y * height)))
            offset = (y * width + x) * 4
            total[0] += pixels[offset]
            total[1] += pixels[offset + 1]
            total[2] += pixels[offset + 2]
            count += 1
        if not count:
            continue
        red, green, blue_channel = [channel / count for channel in total]
        # The star is blue and violet; the helmet is white and the visor
        # is a dark blue, so the violet has to be picked out on its own.
        if blue_channel > 0.30 and red > blue_channel * 0.35 and green < blue_channel * 0.75:
            blue.append(face)

    if not blue:
        print("YXZ_STAR " + json.dumps({"faces": 0}))
        bm.free()
        return

    points = [v.co.copy() for face in blue for v in face.verts]
    low = [round(min(p[i] for p in points), 4) for i in range(3)]
    high = [round(max(p[i] for p in points), 4) for i in range(3)]
    middle = Vector([round((low[i] + high[i]) / 2, 4) for i in range(3)])
    relative = middle - centre
    print("YXZ_STAR " + json.dumps({
        "faces": len(blue),
        "low": low,
        "high": high,
        "centre": list(middle),
        "radius": round(relative.length, 4),
        "elevation": round(math.degrees(math.asin(relative.z / relative.length)), 1),
        "bearing": round(math.degrees(math.atan2(relative.y, relative.x)), 1),
    }))
    bm.free()


if __name__ == "__main__":
    main()
