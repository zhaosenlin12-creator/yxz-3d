"""Find the sheets of the scan that lie turned away from the camera.

The scan arrives as a couple of hundred separate sheets that fit together,
and a handful of them are folded back on themselves and left lying over the
finished surface.  A folded sheet presents its back to the camera, so the
renderer lights it as if it were a face, it comes out a shade brighter than
the body it is lying on, and it draws a hard straight edge where it ends.
That is the whole of the shattered look: not a torn model, but a few pieces
of one lying on top of it.

They cannot be picked out.  A ray fired into a sheet that is turned away
passes straight through it and reports whatever is behind, so every pick
lands on clean geometry and every pick comes back clean.  Picking is not the
answer and never was.

What identifies them is the pair of facts together.  A sheet like this is
turned away from the front of the character -- its normals point backwards
-- and it is in front of the body it is lying on, so the camera reaches it
first.  The first fact alone is useless: the back of the head and the
inside of the ear cups are turned away too, and they are correct.  The
second fact is what separates them, and it is checked by rendering: the
candidate is painted in colour and the picture says whether the camera can
see it at all.

So the pieces are found in two steps.  The mesh is welded by position --
the scan's sheets are separate only because the cut along a seam left two
vertices where there should be one -- which gives the real pieces.  Each
piece is measured for how much of it faces the front, and the ones that are
mostly facing backwards are the candidates.  Rendering them settles it.

Usage:
  from yxz_shards import find_shards
"""

from __future__ import annotations

import bmesh
import numpy as np
from mathutils import Vector


# The character's front, as an axis.  The cleaned scan puts it on +X.
FRONT = Vector((1.0, 0.0, 0.0))

# How close two vertices have to be to count as one vertex.  This is well
# under the size of a triangle -- the scan's are about 0.005 across -- so it
# closes a seam that was cut without collapsing a surface.
WELD = 0.0006

# A piece is a candidate when this much of it faces backwards.  A piece of
# folded sheet is almost entirely turned away, while a piece of the body
# that happens to wrap round to the far side is not: it is a shell, and the
# far side of a shell is a minority of it.
TURNED_AWAY = 0.75

# Below this many faces a piece is not worth the risk of a removal.  A scrap
# of a few triangles is invisible and a large removal is not.
MIN_FACES = 40


def weld_by_position(bm, threshold=WELD):
    """Merge the duplicate vertices a cut seam leaves behind."""
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=threshold)
    bm.faces.ensure_lookup_table()


def components(bm):
    """The connected pieces of a mesh, biggest first."""
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
    groups.sort(key=len, reverse=True)
    return groups


def front_axis(front):
    """The facing direction as a 3D axis.

    The direction is given the way the command line gives it -- two numbers,
    because the front of the character is a direction in the ground plane
    and the up axis is not part of the question.  A surface that faces the
    front of the character is one whose normal points along it, whether it
    is the chest or the top of the head.
    """
    values = list(front)
    while len(values) < 3:
        values.append(0.0)
    axis = Vector(values[:3])
    return axis.normalized() if axis.length > 1e-9 else Vector(FRONT)


def facing_ratio(group, front=FRONT):
    """How much of a piece faces the front, by area."""
    front = front_axis(front)
    towards = 0.0
    away = 0.0
    for face in group:
        normal = face.normal
        if normal.length < 1e-9:
            continue
        area = face.calc_area()
        if normal.dot(front) >= 0.0:
            towards += area
        else:
            away += area
    total = towards + away
    if total <= 0.0:
        return 0.0, 0.0
    return towards / total, away / total


def bbox(group):
    points = np.array([[c for vertex in face.verts for c in vertex.co]
                       for face in group])
    return points.min(axis=0), points.max(axis=0)


def uv_rect(group, uv_layer):
    us = []
    vs = []
    for face in group:
        for loop in face.loops:
            us.append(loop[uv_layer].uv.x)
            vs.append(loop[uv_layer].uv.y)
    if not us:
        return None
    return [round(min(us), 4), round(min(vs), 4),
            round(max(us), 4), round(max(vs), 4)]


def find_shards(mesh, front=FRONT, turned_away=TURNED_AWAY,
                min_faces=MIN_FACES, weld=WELD):
    """The pieces of the scan that lie turned away from the front.

    The mesh itself is left exactly as it was.  The welding happens on a
    throwaway copy, because welding a seam shut is destructive -- it takes
    eleven thousand pieces down to a few hundred and pulls the fringe of
    the surface out of shape -- and here the pieces are only being counted.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    weld_by_position(bm, weld)
    uv_layer = bm.loops.layers.uv.active

    shards = []
    stats = {"pieces": 0, "largest": 0, "turnedAway": 0, "kept": 0}
    for group in components(bm):
        stats["pieces"] += 1
        stats["largest"] = max(stats["largest"], len(group))
        towards, away = facing_ratio(group, front)
        if away < turned_away:
            continue
        stats["turnedAway"] += 1
        if len(group) < min_faces:
            continue
        low, high = bbox(group)
        shards.append({
            "faces": group,
            "count": len(group),
            "towards": round(towards, 3),
            "low": [round(float(c), 4) for c in low],
            "high": [round(float(c), 4) for c in high],
            "uv": uv_rect(group, uv_layer),
        })
    bm.free()
    stats["kept"] = len(shards)
    return shards, stats
