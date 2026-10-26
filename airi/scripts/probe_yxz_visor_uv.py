"""Where the visor is painted, and what it is painted with.

The visor is split into several separate pieces of the scan, and each
piece samples a different part of the texture atlas.  That is why the
screen is two colours with a ragged join down the middle of it: the two
halves are not two halves of one picture, they are two different
pictures, and the join between them is the edge of the scan.

This prints, for every piece of the visor, the rectangle of the atlas it
covers and the average colour of that rectangle, and it prints the same
for the whole of the rest of the model, so it is possible to see whether
the rectangle a piece of visor covers is shared with anything else.

Usage:
  blender -b -P scripts/probe_yxz_visor_uv.py -- \
    --glb <glb> --centre 0.038,-0.001,0.094 [--inner 0.20] [--outer 0.295]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def islands(bm):
    bm.faces.ensure_lookup_table()
    unvisited = set(bm.faces)
    groups = []
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
    glb = Path(value_after("--glb"))
    out = Path(value_after("--out", "docs/yxz-audit/visor-uv"))
    out.mkdir(parents=True, exist_ok=True)
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    inner = float(value_after("--inner", "0.20"))
    outer = float(value_after("--outer", "0.295"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    image = None
    for candidate in bpy.data.images:
        if candidate.name.startswith("Color"):
            image = candidate
            break
    if image is None:
        raise SystemExit("no colour texture found")
    width = image.size[0]
    height = image.size[1]
    pixels = list(image.pixels[:])

    def sample(u: float, v: float) -> tuple[float, float, float]:
        x = max(0, min(width - 1, int(u * width)))
        # Blender's images are bottom up; the atlas is written top down.
        y = max(0, min(height - 1, int((1.0 - v) * height)))
        at = (y * width + x) * 4
        return pixels[at], pixels[at + 1], pixels[at + 2]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    groups = islands(bm)

    pieces = []
    for number, group in enumerate(groups):
        faces = []
        for face in group:
            middle = face.calc_center_median()
            radius = (middle - centre).length
            if inner <= radius <= outer:
                faces.append(face)
        if len(faces) < 8:
            continue
        us = []
        vs = []
        for face in faces:
            for loop in face.loops:
                us.append(loop[uv_layer].uv.x)
                vs.append(loop[uv_layer].uv.y)
        # A coarse sample of the rectangle the piece covers.
        u0 = min(us)
        u1 = max(us)
        v0 = min(vs)
        v1 = max(vs)
        total = [0.0, 0.0, 0.0]
        count = 0
        for i in range(12):
            for j in range(12):
                colour = sample(u0 + (u1 - u0) * (i + 0.5) / 12,
                                v0 + (v1 - v0) * (j + 0.5) / 12)
                total[0] += colour[0]
                total[1] += colour[1]
                total[2] += colour[2]
                count += 1
        pieces.append({
            "island": number,
            "faces": len(faces),
            "u0": round(u0, 4), "u1": round(u1, 4),
            "v0": round(v0, 4), "v1": round(v1, 4),
            "mean": [round(c / count, 3) for c in total],
        })
    pieces.sort(key=lambda piece: -piece["faces"])

    # The same for the model as a whole, so a rectangle that is shared is
    # known to be shared.
    everything = []
    for face in bm.faces:
        for loop in face.loops:
            everything.append((loop[uv_layer].uv.x, loop[uv_layer].uv.y))
    print("YXZ_ATLAS %dx%d  uv %s" % (
        width, height,
        "%.3f..%.3f / %.3f..%.3f" % (
            min(p[0] for p in everything), max(p[0] for p in everything),
            min(p[1] for p in everything), max(p[1] for p in everything))))
    for piece in pieces[:8]:
        print("YXZ_VISOR_UV " + json.dumps(piece))
    (out / "uv.json").write_text(json.dumps(pieces, indent=1), encoding="utf-8")
    bm.free()


if __name__ == "__main__":
    main()
