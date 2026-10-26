"""Which shells of the scan are torn scraps rather than parts of the toy?

A scan is stitched from pieces, and where two pieces met the stitch tore.
The tear leaves a scrap with a feathered, spiked outline hanging off the
surface -- on screen it is the dark fringe round the crown of the head and
the dust on the shoulders.

The measure is the outline.  A part of the toy has an outline: a closed
curve with a few edges, each one long.  A scrap has an outline made of
short edges with the direction changing sharply at nearly every one of
them, because the tear went back and forth across the grain of the
surface.  So the two things worth counting are how much of the shell's
edge is boundary, and how often that boundary doubles back on itself.

  boundary density  =  boundary edges / faces
  spike share        =  corners where the boundary turns more than 70 deg
                       / boundary corners

Usage:
  blender -b -P scripts/probe_yxz_flakes.py -- --glb <glb> [--out <json>]
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

import bpy
import bmesh
import numpy as np
from mathutils import Vector


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


def boundary_stats(group):
    """The outline of a shell: its edges, its corners and its spikes."""
    faces = set(group)
    boundary = {}
    for face in faces:
        for edge in face.edges:
            other = [f for f in edge.link_faces if f not in faces]
            if other:
                continue
            boundary[edge] = face
    if not boundary:
        return None
    verts = {}
    for edge in boundary:
        for vert in edge.verts:
            verts[vert] = None
    # Walk the boundary as loops.
    adjacency = defaultdict(list)
    for edge in boundary:
        a, b = edge.verts
        adjacency[a].append((b, edge))
        adjacency[b].append((a, edge))
    spikes = 0
    corners = 0
    lengths = []
    for edge in boundary:
        lengths.append(edge.calc_length())
    # Count the sharp turns: at a corner the two edges leave in very
    # different directions.
    for vert, links in adjacency.items():
        if len(links) != 2:
            continue
        corners += 1
        (a, ea), (b, eb) = links
        va = (a.co - vert.co).normalized()
        vb = (b.co - vert.co).normalized()
        if va.dot(vb) < math.cos(math.radians(70)):
            spikes += 1
    return {
        "faces": len(faces),
        "boundaryEdges": len(boundary),
        "boundaryLength": round(sum(lengths), 5),
        "meanEdgeLength": round(sum(lengths) / max(len(lengths), 1), 6),
        "corners": corners,
        "spikes": spikes,
    }


def main():
    source = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    rows = []
    for number, group in enumerate(shells(bm)):
        stats = boundary_stats(group)
        if stats is None:
            continue
        points = np.array([[v.co.x, v.co.y, v.co.z] for f in group
                           for v in f.verts])
        low = points.min(axis=0)
        high = points.max(axis=0)
        stats["shell"] = number
        stats["low"] = [round(float(v), 4) for v in low]
        stats["high"] = [round(float(v), 4) for v in high]
        stats["density"] = round(stats["boundaryEdges"] / max(stats["faces"], 1), 4)
        stats["spikeShare"] = round(stats["spikes"] / max(stats["corners"], 1), 4)
        stats["area"] = round(float(sum(f.calc_area() for f in group)), 6)
        rows.append(stats)

    rows.sort(key=lambda row: -row["density"])
    print("YXZ_FLAKES " + json.dumps({
        "shells": len(rows),
        "top": rows[:40],
    }))
    # Everything small enough to be a scrap, for a second look.
    small = [r for r in rows if r["faces"] < 1500]
    small.sort(key=lambda row: -row["density"])
    print("YXZ_FLAKE_SMALL " + json.dumps(small[:80]))


main()
