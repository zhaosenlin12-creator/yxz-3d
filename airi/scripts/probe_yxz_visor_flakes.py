"""Which shells of the scan are white scraps lying on the visor?

The visor is the one big dark panel on the front of the head, and on
screen it carries two bright marks that do not belong to it: a jagged
white crack running in from the left edge, and a bar of white light
across the middle.  Both read as broken glass, which is the opposite of
what the panel is.

Those marks may be paint in the atlas or scraps of geometry lying on
top of the panel, and the two are fixed in completely different places.
So each shell is measured twice: where it is, and what colour the
atlas says it is.

Usage:
  blender -b -P scripts/probe_yxz_visor_flakes.py -- --glb <glb>
"""

from __future__ import annotations

import json
import sys

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


def main():
    source = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    texture = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            texture = image
            break
    pixels = None
    if texture is not None:
        texture.pixels  # touch, so Blender loads the file
        width, height = texture.size
        pixels = list(texture.pixels)

    def sample(u, v):
        if pixels is None:
            return None
        x = min(width - 1, max(0, int(u * width)))
        y = min(height - 1, max(0, int(v * height)))
        index = (y * width + x) * 4
        return [round(pixels[index + i], 3) for i in range(3)]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active

    rows = []
    for number, group in enumerate(shells(bm)):
        low = [float("inf")] * 3
        high = [float("-inf")] * 3
        colours = []
        for face in group:
            for vert in face.verts:
                for axis in range(3):
                    value = vert.co[axis]
                    low[axis] = min(low[axis], value)
                    high[axis] = max(high[axis], value)
            if uv_layer is not None:
                loop = face.loops[0]
                colours.append(sample(loop[uv_layer].uv.x, loop[uv_layer].uv.y))
        colours = [c for c in colours if c is not None]
        if not colours:
            continue
        mean = [
            round(sum(c[i] for c in colours) / len(colours), 3) for i in range(3)
        ]
        luminance = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
        rows.append({
            "shell": number,
            "faces": len(group),
            "low": [round(v, 4) for v in low],
            "high": [round(v, 4) for v in high],
            "mean": mean,
            "luma": round(luminance, 3),
        })

    # The visor panel: in front of the head, between the crown and the jaw.
    front = [
        row for row in rows
        if row["low"][1] < -0.16 and row["high"][1] < -0.02
        and row["low"][2] > 0.02 and row["high"][2] < 0.34
    ]
    front.sort(key=lambda row: -row["luma"])
    print("YXZ_VISOR_FRONT " + json.dumps({"shells": len(front), "rows": front[:60]}))

    bright = [row for row in front if row["luma"] > 0.45]
    bright.sort(key=lambda row: row["faces"])
    print("YXZ_VISOR_BRIGHT " + json.dumps(bright[:60]))
    bm.free()


main()
