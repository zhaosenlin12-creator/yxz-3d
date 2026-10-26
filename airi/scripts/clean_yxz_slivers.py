"""Take the wreck of the old halo off the character's head, for good.

The head is whole now, but there is still something standing over it,
and it is what makes the character read as shattered rather than as a
figure in a helmet.  Three kinds of it are left, and each is told apart
from the character by a different number:

* Sheets.  The scan's surface panels come apart along their joins and
  the pieces that lift are a fraction of a millimetre thick with a hard
  outline all the way round.  A sheet shows up as a small axis in the
  singular values of its own points; a panel, a wing, an eye --
  anything with volume -- does not.  They are the chips that stand in
  the hair, and the dark hairlines across the helmet are the same
  thing seen edge on.

* Blades.  The remains of the old halo are four crescents a couple of
  thousand triangles each, and no thickness test touches a piece that
  big.  They are taken on a different ground: they float.  Every part
  of the character is welded to the body, and a crescent hanging over
  the crown touches nothing at all.  The height keeps the wings, which
  float too but reach below the neck.

* Scraps.  What is left over the crown after the blades are gone is a
  curled sliver welded to the helmet by a chance contact, too thick
  for the sheet test and too attached for the float test.  It is the
  one piece with no test of its own, and it is caught by the plainest
  thing left: it is a fragment, and it is up over the head.

Usage:
  blender -b -P scripts/clean_yxz_slivers.py -- \
    --source <glb> --output <glb> [--report-only]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


# How thin a shell has to be, as a fraction of the character's own
# height.  The model is about one unit tall, so this is a fraction of a
# millimetre at the scale the helmet is seen from -- thinner than the
# panels that lift, thicker than the hairline triangles the exporters
# produce.
THIN_FRACTION = 0.0016

# A sliver has to be small as well as thin.  The count is in faces: a
# lifted panel is a patch of a dozen triangles, while anything with a
# silhouette of its own is hundreds.
MAX_FACES = 900


def max_faces():
    """The face ceiling, overridable so a sweep can be run over it."""
    return int(value_after("--max-faces", MAX_FACES))

# The standing sheets are a fault of the head, not of the whole figure.
# Everything below the shoulders is left alone whatever it measures,
# because down there the scan's own surface is made of small thin
# panels -- the knee pads, the boot soles, the wing edges -- and those
# are the design rather than debris.
MIN_Z = 0.24

# The bigger half of the wreck is not thin.  It arrives as four crescent
# blades a couple of thousand triangles each -- the remains of the old
# halo -- and no thickness test touches a piece that size, so they are
# taken on a different ground: they float.  Every part of the character
# is welded to the body, and a blade hanging over the crown touches
# nothing at all, so a shell whose nearest approach to the body is more
# than a weld's width away is not attached to anything.
#
# The height is what keeps the wings.  They float too, and by a wider
# margin than the blades do, but they hang off the shoulders: every one
# of them reaches below the neck, and no blade does.
FLOAT_MIN_Z = 0.19

# How close counts as touching.  The clean pass welds at fifteen
# thousandths, so anything within a few thousandths shares its position
# with the body and anything beyond it does not.
FLOAT_CELL = 0.004

# A scrap is the plain case: a fragment that sits entirely above the
# neck.  Nothing of the character does except the ear discs and the
# panels of the helmet that reach down past it, and those are far
# larger than any fragment -- which is what the ceiling is for.
CROWN_MIN_Z = 0.24
CROWN_MAX_FACES = 2000

# The one thing on the head that must never be taken away is the mark
# on the forehead.  The scan gives the star a patch of the atlas of its
# own, and the cap of the helmet that carries it is a separate piece
# from the rest of the shell -- it floats, and it is up over the
# crown, and by every other measure it is debris.  It is not debris:
# take it and the star goes with it, and the head is left with a torn
# edge where the cap was.
#
# So the star's patch is a promise: nothing wearing it is debris.
KEEP = [
    (0.2156, 0.1636, 0.2913, 0.2408),
]

# How much of a shell's own patch has to sit on a kept patch before the
# shell is left alone.  A shell that only brushes the star's patch is
# not the star's cap; one that is mostly on it is.
KEEP_OVERLAP = 0.30


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
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


def thickness_of(group):
    """The smallest dimension of a shell, from the points it is made of."""
    points = np.array([list(face.calc_center_median()) for face in group])
    if len(points) < 3:
        return 0.0
    points = points - points.mean(axis=0)
    # Full matrices: the shells are tiny, and a reduced form would throw
    # away the axis that is exactly the one being measured.
    singular = np.linalg.svd(points, compute_uv=False)
    return float(singular[2])


def bounds_of(group):
    """The box a shell sits in."""
    low = []
    high = []
    for axis in range(3):
        values = [vertex.co[axis] for face in group for vertex in face.verts]
        low.append(min(values))
        high.append(max(values))
    return low, high


def span_of(low, high):
    """The rough size of a box, for ranking what to report."""
    return ((high[0] - low[0]) * (high[1] - low[1]) * (high[2] - low[2])) ** 0.5


def rect_of(group, uv_layer):
    """The rectangle of the atlas a shell is painted with."""
    us = []
    vs = []
    for face in group:
        for loop in face.loops:
            us.append(loop[uv_layer].uv.x)
            vs.append(loop[uv_layer].uv.y)
    if not us:
        return None
    return (min(us), min(vs), max(us), max(vs))


def overlap(a, b):
    """How much of the smaller rectangle is covered by the larger."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return (width * height) / min(area_a, area_b)


def is_kept(rect):
    """Is this patch of the atlas one the character is wearing?"""
    if rect is None:
        return False
    return any(overlap(rect, patch) >= KEEP_OVERLAP for patch in KEEP)


def bucket(points):
    """The body, indexed by the grid cell each of its points falls in."""
    keys = np.floor(points / FLOAT_CELL).astype(np.int64)
    table = {}
    for row, key in enumerate(map(tuple, keys)):
        table.setdefault(key, []).append(row)
    return table


def floats_clear_of(points, table, body_points):
    """Is this shell nowhere near the body at all?

    The body has a hundred thousand points and the shell has thousands,
    so the two are not compared face to face.  The body is bucketed into
    cells and only the twenty-seven cells around each of the shell's
    points are looked at.
    """
    for point in points:
        base = np.floor(point / FLOAT_CELL).astype(np.int64)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    rows = table.get((base[0] + dx, base[1] + dy, base[2] + dz))
                    if rows:
                        near.append(body_points[rows])
        if not near:
            continue
        block = np.concatenate(near)
        if float(np.sqrt(((point - block) ** 2).sum(axis=1)).min()) <= FLOAT_CELL:
            return False
    return True


def census(bm, height):
    """The slivers on the mesh, largest outline first."""
    groups = shells(bm)
    body = max(groups, key=len)
    limit = height * THIN_FRACTION
    found = []
    for number, group in enumerate(groups):
        if group is body or len(group) > MAX_FACES:
            continue
        thin = thickness_of(group)
        if thin > limit:
            continue
        low, high = bounds_of(group)
        found.append({
            "shell": number,
            "faces": len(group),
            "thickness": round(thin, 5),
            "low": [round(value, 4) for value in low],
            "high": [round(value, 4) for value in high],
            "span": round(span_of(low, high), 4),
        })
    found.sort(key=lambda item: item["span"], reverse=True)
    return found


def clean(mesh, apply_changes=True, ceiling=MAX_FACES):
    """Remove the thin standing sheets, and say which ones they were."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    corners = np.array([list(vertex.co) for vertex in bm.verts])
    height = float(corners[:, 2].max() - corners[:, 2].min())
    groups = shells(bm)
    body = max(groups, key=len)
    body_points = np.array([
        list(vertex.co) for face in body for vertex in face.verts
    ])
    table = bucket(body_points)
    limit = height * THIN_FRACTION

    doomed = []
    taken = []
    skipped_low = 0
    blades = 0
    spared = 0
    uv_layer = bm.loops.layers.uv.active
    for number, group in enumerate(groups):
        if group is body:
            continue
        if is_kept(rect_of(group, uv_layer)):
            # The star on the forehead, or a piece of the cap that
            # carries it.  Not debris, whatever else it looks like.
            spared += len(group)
            continue
        low, high = bounds_of(group)
        thin = thickness_of(group)
        points = np.array([
            list(vertex.co) for face in group for vertex in face.verts
        ])
        if low[2] >= CROWN_MIN_Z and len(group) <= CROWN_MAX_FACES:
            # A fragment, up over the head, small enough to be one.
            kind = "scrap"
        elif low[2] >= FLOAT_MIN_Z and floats_clear_of(points, table, body_points):
            # The crescent remains of the old halo: not attached to
            # anything, and too high to be a wing.
            kind = "blade"
            blades += 1
        elif thin <= limit and len(group) <= ceiling and high[2] >= MIN_Z:
            # A lifted panel, standing out of the helmet.
            kind = "sheet"
        elif thin <= limit and len(group) <= ceiling:
            skipped_low += len(group)
            continue
        else:
            continue
        doomed.extend(group)
        taken.append({
            "shell": number,
            "faces": len(group),
            "kind": kind,
            "thickness": round(thin, 5),
            "low": [round(value, 4) for value in low],
            "high": [round(value, 4) for value in high],
            "span": round(span_of(low, high), 4),
        })
    taken.sort(key=lambda item: item["span"], reverse=True)

    report = {
        "height": round(height, 4),
        "thinLimit": round(limit, 5),
        "minZ": MIN_Z,
        "slivers": len(taken),
        "faces": len(doomed),
        "facesBelowHead": skipped_low,
        "blades": blades,
        "sparedFaces": spared,
        "sample": taken[:30],
    }
    if apply_changes and doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
        bm.to_mesh(mesh)
        mesh.update()
        report["afterFaces"] = len(mesh.polygons)
    bm.free()
    return report


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    output.parent.mkdir(parents=True, exist_ok=True)
    report_only = "--report-only" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    report = clean(body.data, apply_changes=not report_only, ceiling=max_faces())
    print("YXZ_SLIVERS " + json.dumps(report))
    if not report_only:
        bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")


if __name__ == "__main__":
    main()
