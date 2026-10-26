"""What is on the head, column by column.

The rebuilt crown is a cap that has to sit on a shell that was torn.  The
cap is drawn at one radius and the old shell is drawn at another, and
where the two disagree the old shell shows through the cap's own
shoulder -- which is the drift of torn white pieces round the front of
the helmet.

So this prints the shape of the head as it is: for every bearing round
the head, the elevations at which there is shell, the elevations at
which there is visor, and how far out from the middle of the head each
of those pieces stands.

Usage:
  blender -b -P scripts/probe_yxz_crown_profile.py -- \
    --glb <glb> [--centre 0.038,-0.001,0.094] [--columns 48]
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
    glb = Path(value_after("--glb"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    columns = int(value_after("--columns", "48"))
    limit = float(value_after("--limit", "0.34"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    # Every face on the head, in terms of bearing and elevation.
    samples = []
    for face in bm.faces:
        middle = face.calc_center_median()
        offset = middle - centre
        distance = offset.length
        if distance > limit or distance < 0.05:
            continue
        direction = offset.normalized()
        phi = math.atan2(direction.y, direction.x) % math.tau
        theta = math.degrees(math.asin(max(-1.0, min(1.0, direction.z))))
        samples.append((phi, theta, distance, face))

    # The visor is the only dark thing on the head.
    uv_layer = bm.loops.layers.uv.active
    pixels, width, height = None, 0, 0
    for material in body.data.materials:
        if not material or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                image = node.image
                width, height = image.size
                pixels = [0.0] * (width * height * 4)
                image.pixels.foreach_get(pixels)
                break
        if pixels:
            break

    def luma(face):
        if pixels is None or uv_layer is None:
            return None
        total = 0.0
        count = 0
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = min(width - 1, max(0, int(uv.x * width)))
            y = min(height - 1, max(0, int(uv.y * height)))
            offset = (y * width + x) * 4
            total += (0.2126 * pixels[offset] + 0.7152 * pixels[offset + 1]
                      + 0.0722 * pixels[offset + 2])
            count += 1
        return total / count if count else None

    visor = []
    shell = []
    for phi, theta, distance, face in samples:
        value = luma(face)
        if value is not None and value < 0.42:
            visor.append((phi, theta, distance))
        else:
            shell.append((phi, theta, distance))

    def in_column(entry, column):
        step = math.tau / columns
        centre_angle = math.tau * (column + 0.5) / columns
        delta = (entry[0] - centre_angle + math.tau) % math.tau
        return delta < step

    def spans(entries, column):
        """The elevations of a column that have something on them."""
        picked = sorted(e[1] for e in entries if in_column(e, column))
        if not picked:
            return []
        out = []
        start = previous = picked[0]
        for value in picked[1:]:
            if value - previous > 3.0:
                out.append((round(start, 1), round(previous, 1)))
                start = value
            previous = value
        out.append((round(start, 1), round(previous, 1)))
        return out

    def radii(entries, column):
        picked = [e[2] for e in entries if in_column(e, column)]
        if not picked:
            return None
        return {"min": round(min(picked), 4), "max": round(max(picked), 4)}

    table = []
    for column in range(columns):
        phi = math.degrees(math.tau * (column + 0.5) / columns)
        table.append({
            "phi": round(phi, 1),
            "shell": spans(shell, column),
            "visor": spans(visor, column),
            "shellR": radii(shell, column),
            "visorR": radii(visor, column),
        })

    print("YXZ_PROFILE " + json.dumps({
        "glb": str(glb),
        "columns": columns,
        "shellFaces": len(shell),
        "visorFaces": len(visor),
        "table": table,
    }))
    bm.free()


if __name__ == "__main__":
    main()
