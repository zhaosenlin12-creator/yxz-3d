"""What colour is the litter, and what colour is the design?

The flake pass keeps a chip when it looks painted, on the grounds that
the star on the forehead and the blue trim on the wings are painted and
must survive.  That test is a dark-chip trap: the chips are UV-mapped
into the dark parts of the atlas, so they look painted too, and half
the litter gets kept and the shell comes out freckled.

This prints the two populations side by side -- the big pieces that are
the design, and the small flat chips lying on them -- so the threshold
that tells them apart can be read off the data instead of guessed.

Usage:
  blender -b -P scripts/probe_yxz_flake_colour.py -- \
    --source <glb> [--rows 30]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree


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


def flatness(points):
    if len(points) < 3:
        return 0.0
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
    array -= array.mean(axis=0)
    singular = np.linalg.svd(array, compute_uv=False)
    return float(singular[2]) * 2.0


def load_atlas():
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


def chip_colour(atlas, uv_layer, group):
    """Mean and spread of the atlas colour under one island."""
    samples = []
    for face in group:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = int(min(max(uv.x, 0.0), 1.0) * (atlas.shape[1] - 1))
            y = int(min(max(uv.y, 0.0), 1.0) * (atlas.shape[0] - 1))
            samples.append(atlas[y, x][:3])
    if not samples:
        return None
    mean = np.mean(np.array(samples, dtype=np.float32), axis=0)
    spread = np.max(np.array(samples, dtype=np.float32), axis=0) - np.min(
        np.array(samples, dtype=np.float32), axis=0)
    return [round(float(v), 4) for v in mean], [round(float(v), 4) for v in spread]


def describe(label, rows):
    print("YXZ_POP " + json.dumps({
        "population": label,
        "islands": len(rows),
        "faces": sum(row[0] for row in rows),
    }))
    for faces, mean, spread, *_rest in rows[:30]:
        chroma = round(max(mean) - min(mean), 4)
        value = round(max(mean), 4)
        print("YXZ_POP_ROW " + json.dumps({
            "faces": faces, "rgb": mean, "chroma": chroma,
            "value": value, "spread": round(max(spread), 4)}))


def main() -> None:
    source = Path(value_after("--source"))
    thin = float(value_after("--thin", "0.008"))
    max_faces = int(value_after("--max-faces", "150"))
    gap = float(value_after("--gap", "0.004"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    groups = islands(bm)
    big = [group for group in groups if len(group) > max_faces]
    small = [group for group in groups if len(group) <= max_faces]

    design_points = [v.co.copy() for group in big for face in group
                     for v in face.verts]
    tree = KDTree(len(design_points))
    for index, point in enumerate(design_points):
        tree.insert(point, index)
    tree.balance()

    atlas = load_atlas()
    uv_layer = bm.loops.layers.uv.active

    chip_rows = []
    painted_design = []
    for group in small:
        points = [v.co.copy() for face in group for v in face.verts]
        if len(points) < 3 or flatness(points) > thin:
            continue
        closest = min(tree.find(Vector(p))[2] for p in points)
        if closest > gap:
            continue
        colour = chip_colour(atlas, uv_layer, group)
        if colour is None:
            continue
        chip_rows.append((len(group), colour[0], colour[1], closest))

    for group in big:
        colour = chip_colour(atlas, uv_layer, group)
        if colour is None:
            continue
        mean = colour[0]
        if max(mean) - min(mean) > 0.12:
            painted_design.append((len(group), mean, colour[1]))

    chip_rows.sort(key=lambda row: (row[1][0] + row[1][1] + row[1][2]))
    painted_design.sort(key=lambda row: -row[0])
    describe("chip", chip_rows)
    describe("paintedDesign", painted_design)

    # How much of the litter is dark, and how much is genuinely coloured?
    buckets = {"dark": 0, "grey": 0, "chroma": 0, "bright": 0}
    for faces, mean, spread, gap_to_design in chip_rows:
        chroma = max(mean) - min(mean)
        value = max(mean)
        if value < 0.22:
            buckets["dark"] += 1
        elif chroma < 0.10:
            buckets["grey"] += 1
        elif chroma < 0.22:
            buckets["chroma"] += 1
        else:
            buckets["bright"] += 1
    print("YXZ_POP_BUCKETS " + json.dumps(buckets))

    # The decision the pass actually turns on: a chip is kept when it is
    # bright and saturated, because that is what the star and the trim
    # look like.  Count the chips on each side of that line.
    histogram = {}
    for faces, mean, spread, gap_to_design in chip_rows:
        chroma = max(mean) - min(mean)
        value = max(mean)
        for threshold in (0.22, 0.30, 0.35, 0.45):
            if value > threshold and chroma > 0.18:
                histogram["keepAt%.2f" % threshold] = \
                    histogram.get("keepAt%.2f" % threshold, 0) + 1
    histogram["chipTotal"] = len(chip_rows)
    print("YXZ_POP_KEEP " + json.dumps(histogram))

    value_hist = [0] * 10
    for faces, mean, spread, gap_to_design in chip_rows:
        value_hist[min(9, int(max(mean) * 10))] += 1
    print("YXZ_POP_VALUE " + json.dumps(value_hist))

    # What do the chips that survive a bright-and-saturated rule look
    # like, size-wise?  If they are all one or two triangles they are
    # still litter, whatever their colour.
    survivors = [(faces, mean, gap_to_design) for faces, mean, spread, gap_to_design in chip_rows
                 if max(mean) > 0.35 and (max(mean) - min(mean)) > 0.18]
    survivors.sort(key=lambda row: -row[0])
    print("YXZ_POP_SURVIVORS " + json.dumps({
        "count": len(survivors),
        "faces": sum(row[0] for row in survivors),
        "big": [{"faces": row[0], "rgb": [round(v, 3) for v in row[1]],
                 "gap": round(row[2], 6)}
                for row in survivors[:15]],
    }))

    # The test that should actually separate them: a chip that is a copy
    # of the surface it lies on is *on* it, to within nothing.  A badge
    # that stands proud of the shell is off it by however proud it is.
    gap_hist = {}
    for faces, mean, spread, gap_to_design in chip_rows:
        bucket = "0" if gap_to_design < 1e-5 else (
            "1e-5" if gap_to_design < 1e-4 else (
            "1e-4" if gap_to_design < 5e-4 else (
            "5e-4" if gap_to_design < 1e-3 else (
            "1e-3" if gap_to_design < 2e-3 else "2e-3+"))))
        gap_hist[bucket] = gap_hist.get(bucket, 0) + 1
    print("YXZ_POP_GAP " + json.dumps(gap_hist))

    # Of the chips that are genuinely off the surface, what are they?
    raised = [(faces, mean, gap_to_design) for faces, mean, spread, gap_to_design in chip_rows
              if gap_to_design > 5e-4]
    raised.sort(key=lambda row: -row[0])
    print("YXZ_POP_RAISED " + json.dumps({
        "count": len(raised),
        "faces": sum(row[0] for row in raised),
        "big": [{"faces": row[0], "rgb": [round(v, 3) for v in row[1]],
                 "gap": round(row[2], 6)} for row in raised[:15]],
    }))
    bm.free()


if __name__ == "__main__":
    main()
