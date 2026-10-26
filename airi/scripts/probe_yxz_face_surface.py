"""Measure the YXZ face surface and the landmarks baked into its texture.

The eyes and mouth are painted onto the helmet texture rather than modelled,
so any replacement geometry has to line up with pixels that already exist.
This probe ray-casts the front surface on a grid, samples the baked colour at
every sample, and reports where the white eye ovals and the red smile sit.

  blender -b -P scripts/probe_yxz_face_surface.py -- --glb <path>
"""

from __future__ import annotations

import json
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class Sampler:
    """Front-surface ray casting plus a barycentric texture lookup."""

    def __init__(self, body):
        mesh = body.data
        mesh.calc_loop_triangles()
        self.mesh = mesh
        self.bvh = BVHTree.FromPolygons(
            [v.co[:] for v in mesh.vertices],
            [tuple(t.vertices) for t in mesh.loop_triangles],
            all_triangles=True,
        )
        self.uv = mesh.uv_layers.active
        self.uv_data = self.uv.data if self.uv else None
        self.triangles = mesh.loop_triangles
        self.image = None
        self.misses = 0
        if mesh.materials and mesh.materials[0] and mesh.materials[0].use_nodes:
            bsdf = mesh.materials[0].node_tree.nodes.get("Principled BSDF")
            if bsdf is None:
                bsdf = next((n for n in mesh.materials[0].node_tree.nodes
                             if "BSDF" in n.bl_idname), None)
            if bsdf and bsdf.inputs["Base Color"].links:
                self.image = bsdf.inputs["Base Color"].links[0].from_node.image
        self.size = (0, 0)
        self.pixels = None
        if self.image:
            self.size = tuple(self.image.size)
            # Image.pixels is a Python property; pulling 16M floats one at a
            # time makes a grid scan take minutes, so bulk-read it once.
            raw = np.empty(len(self.image.pixels), dtype=np.float32)
            self.image.pixels.foreach_get(raw)
            self.pixels = raw.reshape(self.size[1], self.size[0], 4)

    def hit(self, x, z):
        found = self.bvh.ray_cast(Vector((x, -3.0, z)), Vector((0.0, 1.0, 0.0)))
        if found[0] is None:
            self.misses += 1
        # Blender 5.x returns (location, normal, index, object) from ray_cast.
        return found[0], found[2] if len(found) > 2 else None

    def front_y(self, x, z):
        point, _ = self.hit(x, z)
        return None if point is None else point.y

    def color(self, x, z, fallback=(0.0, 0.0, 0.0)):
        point, tri_index = self.hit(x, z)
        if point is None or tri_index is None or self.uv_data is None \
                or self.image is None:
            return fallback
        tri = self.triangles[tri_index]
        v0, v1, v2 = (self.mesh.vertices[i].co.copy() for i in tri.vertices)
        d00, d01 = (v0 - point).dot(v0 - v1), (v0 - point).dot(v0 - v2)
        d11 = (v1 - point).dot(v1 - v2)
        d12 = (v1 - point).dot(v1 - v0)
        denom = d00 * d11 - d01 * d12
        if abs(denom) < 1e-12:
            return fallback
        w1 = (d11 * d00 - d01 * d12) / denom
        w2 = (d00 * d11 - d01 * d12) / denom
        uvs = [self.uv_data[li].uv for li in tri.loops]
        u = uvs[0][0] + w1 * (uvs[1][0] - uvs[0][0]) + w2 * (uvs[2][0] - uvs[0][0])
        v = uvs[0][1] + w1 * (uvs[1][1] - uvs[0][1]) + w2 * (uvs[2][1] - uvs[0][1])
        width, height = self.size
        px = min(width - 1, max(0, int(u * width)))
        py = min(height - 1, max(0, int(v * height)))
        texel = self.pixels[py, px]
        return tuple(to_linear(float(texel[i])) for i in range(3))


def classify(color):
    r, g, b = color
    if r > 0.55 and g > 0.55 and b > 0.55:
        return "white"
    if r > 0.10 and r > g * 2.2 and r > b * 2.2:
        return "red"
    if b > 0.02 and b > r * 1.6 and b > g * 1.2:
        return "navy"
    return None


def largest_blob(labels, colours, accept, z_origin):
    """Bounding box and brightness centroid of the biggest accepted blob."""
    keys = sorted(labels)
    inside = {
        (xi, zi): bool(accept(colours[keys[xi]][zi]))
        for xi in range(len(keys))
        for zi in range(len(labels[keys[0]]))
    }
    seen = set()
    best = None
    for start in inside:
        if not inside[start] or start in seen:
            continue
        stack = [start]
        seen.add(start)
        members = []
        while stack:
            xi, zi = stack.pop()
            members.append((xi, zi))
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = (xi + dx, zi + dz)
                if (neighbour in inside and inside[neighbour]
                        and neighbour not in seen):
                    seen.add(neighbour)
                    stack.append(neighbour)
        if best is None or len(members) > len(best):
            best = members
    if not best:
        return None
    xs = [keys[xi] for xi, _ in best]
    zs = [z_origin + zi * 0.002 for _, zi in best]
    weight = [max(colours[keys[xi]][zi]) for xi, zi in best]
    total = sum(weight) or 1.0
    return {
        "x": [round(min(xs), 4), round(max(xs), 4)],
        "z": [round(min(zs), 4), round(max(zs), 4)],
        "centroid": [round(sum(x * w for x, w in zip(xs, weight)) / total, 4),
                     round(sum(z * w for z, w in zip(zs, weight)) / total, 4)],
        "cells": len(best),
    }


def scan(sampler, x_range, z_range, step):
    """Collect per-label bounding boxes and the depth grid over the same area."""
    boxes = {}
    grid = {}
    labels = {}
    colours = {}
    x = x_range[0]
    while x <= x_range[1] + 1e-9:
        z = z_range[0]
        column = []
        label_row = []
        colour_row = []
        while z <= z_range[1] + 1e-9:
            y = sampler.front_y(x, z)
            rgb = sampler.color(x, z)
            label = classify(rgb)
            if label and y is not None:
                box = boxes.setdefault(label, [x, x, z, z, 0])
                box[0] = min(box[0], x)
                box[1] = max(box[1], x)
                box[2] = min(box[2], z)
                box[3] = max(box[3], z)
                box[4] += 1
            column.append(None if y is None else round(y, 4))
            label_row.append("." if label is None else label[0].upper())
            colour_row.append([round(c, 3) for c in rgb])
            z += step
        grid[round(x, 4)] = column
        labels[round(x, 4)] = label_row
        colours[round(x, 4)] = colour_row
        x += step
    return boxes, grid, labels, colours


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max((o for o in bpy.context.scene.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices))
    body.data.transform(Matrix.Rotation(math.radians(-90.0), 4, "Z"))
    body.data.update()

    sampler = Sampler(body)
    report = {"glb": glb, "imageSize": list(sampler.image.size) if sampler.image else None}
    report["samples"] = {
        "eye_%d_%d" % (round(x * 1000), round(z * 1000)): [
            round(v, 4) for v in sampler.color(x, z)]
        for x, z in ((0.096, 0.154), (0.096, 0.100), (0.000, 0.154),
                     (0.000, 0.100), (0.000, 0.060), (0.180, 0.180))
    }

    eye_boxes, eye_grid, eye_labels, eye_rgb = scan(
        sampler, (0.04, 0.15), (0.10, 0.22), 0.002)
    report["eyeRegion"] = {"labels": eye_boxes, "frontY": eye_grid,
                           "cells": eye_labels, "rgb": eye_rgb}
    report["eyeBlob"] = largest_blob(
        eye_labels, eye_rgb, lambda c: max(c) > 0.45, 0.10)
    report["eyeBlobSoft"] = largest_blob(
        eye_labels, eye_rgb, lambda c: max(c) > 0.22, 0.10)

    mouth_boxes, mouth_grid, mouth_labels, mouth_rgb = scan(
        sampler, (-0.06, 0.06), (0.02, 0.11), 0.002)
    report["mouthRegion"] = {"labels": mouth_boxes, "frontY": mouth_grid,
                             "cells": mouth_labels, "rgb": mouth_rgb}
    report["mouthBlob"] = largest_blob(
        mouth_labels, mouth_rgb,
        lambda c: c[0] > 0.06 and c[0] > c[1] * 2.0 and c[0] > c[2] * 2.0, 0.02)

    print("YXZ_FACE_SURFACE " + json.dumps(report))


if __name__ == "__main__":
    main()
