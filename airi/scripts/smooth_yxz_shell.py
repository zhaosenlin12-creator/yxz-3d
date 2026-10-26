"""Take the scan's fine crumple off the shell.

The face is the worst place the scan went wrong, and at arm's length it
does not look like damage -- it looks like the character is made of
shards.  Zoomed in, the reason is plain: the surface over the cheeks and
the chin is not smooth.  It is covered in small creases and facets a
fraction of a millimetre deep, and a light raking across a shell picks
every one of them out as a bright line with a dark line beside it.  That
is where the scratches across the face come from, and no amount of
removing loose pieces will touch it, because the pieces are not loose.
They are the surface.

So the surface itself is what gets fixed, and gently.  Taubin smoothing
is used rather than plain Laplacian because a plain pass shrinks a mesh:
each pass pulls every vertex towards the average of its neighbours, and
over a closed shell that adds up to a smaller character.  Taubin follows
each shrinking pass with a slightly larger one in the other direction,
which puts the volume back while keeping the high-frequency noise gone.

The amount is measured rather than judged, and it is capped.  Every vertex
that moves is compared with where it started and the pass reports the
largest and mean displacement, so "gentle" is a number that can be
checked against what the eye calls a scratch in the first place.  The cap
is what makes it safe: the scan has sheets of shell lying against other
sheets, and a vertex on one of those has neighbours on both sides of it,
so an uncapped pass pulls it straight through the sheet it is resting on
and tears a hole in the face.  Holding each vertex to a maximum move
removes the fine crumple, which is small, without ever moving anything
far enough to reach through.

Usage:
  blender -b -P scripts/smooth_yxz_shell.py -- \
    --source <glb> --output <glb> [--passes 4] [--lambda 0.35]
    [--max-move 0.0012]
"""

from __future__ import annotations

import json
import sys

import bmesh
import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def neighbours_average(bm, position):
    """Where each vertex's neighbours would put it, in one pass."""
    moved = {}
    for vertex in bm.verts:
        edges = vertex.link_edges
        if not edges:
            moved[vertex.index] = position[vertex.index]
            continue
        total = Vector((0.0, 0.0, 0.0))
        for edge in edges:
            total += position[edge.other_vert(vertex).index]
        moved[vertex.index] = total / len(edges)
    return moved


def step(bm, position, factor):
    """Move every vertex a fraction of the way towards its neighbours."""
    target = neighbours_average(bm, position)
    for vertex in bm.verts:
        vertex.co = position[vertex.index].lerp(target[vertex.index], factor)
    return [vertex.co.copy() for vertex in bm.verts]


def main():
    source = value_after("--source")
    output = value_after("--output")
    passes = int(value_after("--passes", "6"))
    lam = float(value_after("--lambda", "0.5"))
    max_move = float(value_after("--max-move", "0.0012"))
    # The restoring pass is the one that gives the volume back, so it has
    # to be the larger of the two or the shell only shrinks.
    mu = -lam * 1.06

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    report = {"passes": passes, "lambda": lam, "mu": round(mu, 4),
              "maxMove": max_move, "meshes": []}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        before = [vertex.co.copy() for vertex in bm.verts]
        position = list(before)
        for _ in range(passes):
            position = step(bm, position, lam)
            position = step(bm, position, mu)
        for index, vertex in enumerate(bm.verts):
            offset = position[index] - before[index]
            if offset.length > max_move:
                position[index] = before[index] + offset * (max_move
                                                           / offset.length)
        for vertex in bm.verts:
            vertex.co = position[vertex.index]
        moved = [(vertex.co - before[vertex.index]).length
                 for vertex in bm.verts]
        moved = [d for d in moved if d > 0]
        report["meshes"].append({
            "mesh": obj.name,
            "verts": len(bm.verts),
            "meanMove": round(sum(moved) / len(moved), 6) if moved else 0,
            "maxMove": round(max(moved), 6) if moved else 0,
        })
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

    print("SMOOTHED " + json.dumps(report))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


main()
