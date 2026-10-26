"""What is actually sitting on the forehead.

The browser shows a band of bright shards along the top of the visor,
and nothing else in the file says they should be there.  This lists
every island of the mesh that lies over the visor, with the colour it
is painted and how far it stands off the surface below it, so the thing
on screen can be named rather than guessed at.

Usage:
  blender -b -P scripts/probe_yxz_forehead.py -- --source <glb>
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


def main() -> None:
    source = Path(value_after("--source"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    pixels, width, height = None, 0, 0
    for material in body.data.materials:
        if material is None or material.node_tree is None:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                width, height = node.image.size
                pixels = np.empty(width * height * 4, dtype=np.float32)
                node.image.pixels.foreach_get(pixels)
                pixels = pixels.reshape(height, width, 4)
                break
        if pixels is not None:
            break

    def colour_of(face):
        if pixels is None:
            return None
        samples = []
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = int(min(max(uv.x, 0.0), 1.0) * (width - 1))
            y = int(min(max(uv.y, 0.0), 1.0) * (height - 1))
            samples.append(pixels[y][x][:3])
        if not samples:
            return None
        return np.mean(np.array(samples, dtype=np.float32), axis=0)

    # Every point of the mesh, so "how far does this island stand off
    # the surface" is a nearest-neighbour question.
    everything = [v.co.copy() for v in bm.verts]
    tree = KDTree(len(everything))
    for index, point in enumerate(everything):
        tree.insert(point, index)
    tree.balance()

    rows = []
    for group in islands(bm):
        points = [face.calc_center_median() for face in group]
        if not points:
            continue
        average = Vector((sum(p.x for p in points) / len(points),
                          sum(p.y for p in points) / len(points),
                          sum(p.z for p in points) / len(points)))
        relative = average - centre
        radius = relative.length
        if radius > 0.36 or radius < 0.12:
            continue
        if average.z < 0.17:
            continue
        elevation = np.degrees(np.arcsin(relative.z / radius))
        bearing = np.degrees(np.arctan2(relative.y, relative.x))
        colours = [colour_of(face) for face in group]
        colours = [c for c in colours if c is not None]
        mean = np.mean(np.array(colours), axis=0) if colours else None
        spread = float((np.array([p for c in colours for p in c]).reshape(-1, 3)
                        .max(axis=0) - np.array([p for c in colours for p in c])
                        .reshape(-1, 3).min(axis=0)).max()) if colours else 0.0
        rows.append({
            "faces": len(group),
            "at": [round(v, 4) for v in average],
            "radius": round(radius, 4),
            "elevation": round(float(elevation), 1),
            "bearing": round(float(bearing), 1),
            "luma": round(float(0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]), 3)
            if mean is not None else None,
            "rgb": [round(float(v), 3) for v in mean] if mean is not None else None,
        })

    rows.sort(key=lambda row: -row["faces"])
    print("YXZ_FOREHEAD " + json.dumps({
        "islands": len(rows),
        "rows": rows[:40],
    }))
    bm.free()


if __name__ == "__main__":
    main()
