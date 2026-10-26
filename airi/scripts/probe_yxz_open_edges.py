"""Find the open boundaries in the YXZ shell.

A crack in the helmet reads as a dark line because it is a hole: an edge
with only one face on it, so the background shows through.  The scan is
assembled from separate sheets, and where two of them meet they either
overlap or leave a gap, and the gap is what the eye reads as a broken
eggshell.

So the cracks are found by looking for edges that do not have a face on
both sides, and they are reported as clusters with their extent, so that
each one can be dealt with on its own rather than as a mass.

Usage:
  blender -b -P scripts/probe_yxz_open_edges.py -- \
    --glb <glb> [--out <png>] [--min-length 0.002]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def clusters(points, gap=0.02):
    """Group nearby points, so one crack comes back as one entry."""
    groups = []
    cell = max(gap, 1e-6)
    buckets = {}
    for index, point in enumerate(points):
        key = (int(point.x // cell), int(point.y // cell), int(point.z // cell))
        buckets.setdefault(key, []).append(index)

    parent = list(range(len(points)))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for key, members in buckets.items():
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    near.extend(buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ()))
        for index in members:
            for other in near:
                if other <= index:
                    continue
                if (points[index] - points[other]).length < gap:
                    union(index, other)

    groups = {}
    for index in range(len(points)):
        groups.setdefault(find(index), []).append(index)
    return [groups[key] for key in groups]


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    min_length = float(value_after("--min-length", 0.002))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.edges.ensure_lookup_table()

    open_edges = []
    for edge in bm.edges:
        if len(edge.link_faces) == 1 and edge.calc_length() >= min_length:
            open_edges.append(edge)

    if not open_edges:
        print("YXZ_OPEN_EDGES none")
        bm.free()
        return

    midpoints = [(edge.verts[0].co + edge.verts[1].co) * 0.5 for edge in open_edges]
    groups = clusters(midpoints)

    group_of = {}
    for group_index, group in enumerate(groups):
        for member in group:
            group_of[member] = group_index

    report = []
    for group_index, group in enumerate(groups):
        cloud = np.array([list(midpoints[member]) for member in group])
        lengths = [
            edge.calc_length()
            for index, edge in enumerate(open_edges)
            if group_of.get(index) == group_index
        ]
        report.append({
            "edges": len(lengths),
            "length": round(float(sum(lengths)), 4),
            "low": [round(float(value), 4) for value in cloud.min(axis=0)],
            "high": [round(float(value), 4) for value in cloud.max(axis=0)],
        })
    report.sort(key=lambda item: -item["length"])

    total = sum(item["length"] for item in report)
    print("YXZ_OPEN_EDGES clusters=%d edges=%d totalLength=%.4f"
          % (len(report), len(open_edges), total))
    for index, item in enumerate(report[:40]):
        print("YXZ_OPEN_EDGE %d %s" % (index, json.dumps(item)))

    if out:
        keep = set()
        for edge in open_edges:
            for vertex in edge.verts:
                keep.add(vertex.index)
        copy = body.data.copy()
        piece = bmesh.new()
        piece.from_mesh(copy)
        piece.faces.ensure_lookup_table()
        bmesh.ops.delete(
            piece,
            geom=[face for face in piece.faces
                  if not any(vertex.index in keep for vertex in face.verts)],
            context="FACES",
        )
        piece.to_mesh(copy)
        piece.free()
        obj = bpy.data.objects.new("cracks", copy)
        bpy.context.scene.collection.objects.link(obj)
        for target, colour in ((obj, (0.95, 0.15, 0.35, 1.0)),
                               (body, (0.72, 0.75, 0.78, 1.0))):
            target.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            shader = material.node_tree.nodes["Principled BSDF"]
            shader.inputs["Base Color"].default_value = colour
            shader.inputs["Roughness"].default_value = 0.7
            target.data.materials.append(material)

        cam_data = bpy.data.cameras.new("cracks")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = 0.75
        cam = bpy.data.objects.new("cracks", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        cam.location = Vector((0.20, -0.10, 0.15))
        cam.rotation_euler = (math.radians(90), 0, math.radians(90))
        scene = bpy.context.scene
        scene.camera = cam

        key = bpy.data.lights.new("key", type="SUN")
        key.energy = 3.0
        key_obj = bpy.data.objects.new("key", key)
        scene.collection.objects.link(key_obj)
        key_obj.rotation_euler = (math.radians(60), 0, math.radians(50))

        scene.render.resolution_x = 900
        scene.render.resolution_y = 900
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("YXZ_OPEN_EDGES_RENDERED " + str(out))

    bm.free()


if __name__ == "__main__":
    import math
    main()
