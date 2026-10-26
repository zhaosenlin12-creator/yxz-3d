"""How far the seams have to be welded before the shell stops leaking.

The scan arrives as a patchwork: the helmet is a dozen tiles, and the
tiles were cut apart rather than joined, so along every seam between two
of them the surface stops.  Each side of the seam has its own
vertices, and the two sets are a fraction of an edge length apart, so
the seam is a hairline gap rather than a matching pair of edges.

Welding the two sets of vertices together is what closes it, and the
question is how far apart they are.  This measures it: the shell is
welded at a series of distances and the number of open edges left over
is counted each time, so the distance that closes the seams without
swallowing the model whole can be read off rather than guessed.

Usage:
  blender -b -P scripts/probe_yxz_weld.py -- --glb <glb> [--dist 0.001,0.002,...]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def open_edges(bm):
    bm.edges.index_update()
    return [edge for edge in bm.edges if len(edge.link_faces) == 1]


def main():
    source = value_after("--glb")
    distances = [float(value) for value in
                 value_after("--dist", "0.0006,0.0015,0.0025,0.0035,0.005").split(",")]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))
    original = body.data.copy()

    rows = []
    for distance in distances:
        body.data = original.copy()
        bm = bmesh.new()
        bm.from_mesh(body.data)
        before = len(open_edges(bm))
        verts_before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        after = len(open_edges(bm))
        head = 0
        for edge in open_edges(bm):
            if max(vertex.co.z for vertex in edge.verts) > 0.18:
                head += 1
        rows.append({
            "weld": distance,
            "openBefore": before,
            "openAfter": after,
            "headOpen": head,
            "vertsBefore": verts_before,
            "vertsAfter": len(bm.verts),
            "faces": len(bm.faces),
        })
        print("YXZ_WELD " + json.dumps(rows[-1]))
        bm.free()

    print("YXZ_WELD_ALL " + json.dumps(rows))


main()
