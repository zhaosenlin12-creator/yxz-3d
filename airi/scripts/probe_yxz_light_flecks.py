"""Which faces on the visor are painting themselves light?

The visor is one flat navy shape in the atlas, and on the model it is
speckled with pale marks.  Each speck is a face that is taking its
colour from somewhere else in the picture, and the question that decides
what to do about it is which piece of the model it belongs to: a face
that is part of a big panel is part of the design and has to be
re-coloured, while a face that is its own small island is litter and
can simply be taken away.

Usage:
  blender -b -P scripts/probe_yxz_light_flecks.py -- \
    --source <glb> [--box 0.18,-0.16,0.08,0.34,0.16,0.26] [--value 0.62]
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


def load_atlas():
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


def atlas_colour(atlas, uv):
    x = int(min(max(uv.x, 0.0), 1.0) * (atlas.shape[1] - 1))
    y = int(min(max(uv.y, 0.0), 1.0) * (atlas.shape[0] - 1))
    return atlas[y, x][:3]


def main() -> None:
    source = Path(value_after("--source"))
    box = [float(p) for p in
           value_after("--box", "0.18,-0.16,0.08,0.34,0.16,0.26").split(",")]
    value_limit = float(value_after("--value", "0.62"))
    x0, y0, z0, x1, y1, z1 = box

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    atlas = load_atlas()
    if atlas is None:
        print("YXZ_FLECK no atlas")
        return

    owner = {}
    for number, group in enumerate(islands(bm)):
        for face in group:
            owner[face.index] = (number, len(group))

    rows = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if not (x0 <= centre.x <= x1 and y0 <= centre.y <= y1
                and z0 <= centre.z <= z1):
            continue
        colours = []
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = int(min(max(uv.x, 0.0), 1.0) * (atlas.shape[1] - 1))
            y = int(min(max(uv.y, 0.0), 1.0) * (atlas.shape[0] - 1))
            colours.append(atlas[y, x][:3])
        mean = np.mean(np.array(colours, dtype=np.float32), axis=0)
        if float(np.max(mean)) < value_limit:
            continue
        island, size = owner.get(face.index, (-1, 0))
        rows.append({
            "island": island,
            "islandFaces": size,
            "area": round(face.calc_area(), 9),
            "rgb": [round(float(c), 3) for c in mean],
            "at": [round(float(c), 3) for c in centre],
        })

    rows.sort(key=lambda row: -row["islandFaces"])
    light_islands = {}
    for row in rows:
        light_islands[row["island"]] = light_islands.get(row["island"], 0) + 1

    # The place in the atlas the navy of the visor is painted, so the
    # picture can be cropped to it and looked at.
    uv_low = [1.0, 1.0]
    uv_high = [0.0, 0.0]
    navy = 0
    for face in bm.faces:
        centre = face.calc_center_median()
        if not (x0 <= centre.x <= x1 and y0 <= centre.y <= y1
                and z0 <= centre.z <= z1):
            continue
        colours = []
        for loop in face.loops:
            uv = loop[uv_layer].uv
            colours.append(atlas_colour(atlas, uv))
        mean = np.mean(np.array(colours, dtype=np.float32), axis=0)
        if float(np.max(mean)) > 0.40:
            continue
        navy += 1
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv_low[0] = min(uv_low[0], uv.x)
            uv_low[1] = min(uv_low[1], uv.y)
            uv_high[0] = max(uv_high[0], uv.x)
            uv_high[1] = max(uv_high[1], uv.y)
    print("YXZ_FLECK " + json.dumps({
        "box": box,
        "navyFaces": navy,
        "navyUV": [round(v, 4) for v in uv_low] + [round(v, 4) for v in uv_high],
        "lightFaces": len(rows),
        "islandsTouched": len(light_islands),
        "inSmallIslands": sum(1 for row in rows if row["islandFaces"] <= 400),
        "inBigIslands": sum(1 for row in rows if row["islandFaces"] > 400),
        "bigIslands": sorted(
            ({"island": row["island"], "faces": row["islandFaces"],
              "light": light_islands[row["island"]]}
             for row in rows if row["islandFaces"] > 400),
            key=lambda item: item["island"]),
        "sample": rows[:20],
    }))
    bm.free()


if __name__ == "__main__":
    main()
