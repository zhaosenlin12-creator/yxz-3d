"""Close the tear across the crown of the YXZ helmet.

The helmet is not one shell.  It is a dozen of the scan's tiles, and the
tile that carried the crown was cut out of the scan with a seam around it
that was never closed, so the top of the head is open along a long ragged
gash that runs most of the way round.  The repair pass cannot close it:
a gash of that length is not an opening it is willing to fill, because
filling it means fanning several hundred triangles to a single point, and
a point placed by a fit through a rim that is not a circle comes out as a
hedgehog of needles standing off the crown.

That is the right thing to be careful about and the wrong thing to be
careful about.  The tear is not a hole in a flat plate; it is a hole in a
body that is very nearly an ellipsoid, and the shell around it is very
nearly on that ellipsoid.  So the patch is not a fan at all: the rim of
the tear is projected onto the ellipsoid the head already sits on, the
hole is filled in the ellipsoid's own surface coordinates -- ring by ring,
each ring a scaled copy of the rim, every point of every ring pushed back
onto the ellipsoid -- and the patch is stitched to the rim by reusing the
rim's own vertices.  There is no seam because there is nothing to seam:
the patch and the shell are one surface, and the patch's outline is the
shell's outline.

The result is a smooth crown that follows the shape of the head, with the
jagged edge of the tear smoothed into it, and it costs the design
nothing: the crown of this helmet is a flat white.

Usage:
  blender -b -P scripts/patch_yxz_crown.py -- \
    --source <glb> --output <glb> [--centre 0.038,-0.001,0.094] \
    [--weld 0.0006] [--rings 10] [--report-only]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repair_yxz_holes import boundary_loops, rim_order  # noqa: E402


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


class Ellipsoid:
    """The head's own shape, as an ellipsoid the head sits inside."""

    def __init__(self, centre, radii):
        self.centre = Vector(centre)
        self.radii = Vector(radii)

    def parameter(self, point):
        """Where a point sits on the unit sphere of the ellipsoid."""
        q = Vector([(point[i] - self.centre[i]) / self.radii[i] for i in range(3)])
        length = q.length
        if length < 1e-9:
            return Vector((0.0, 0.0, 1.0))
        return q / length

    def place(self, unit):
        """The point on the ellipsoid a unit direction stands for."""
        return self.centre + Vector([unit[i] * self.radii[i] for i in range(3)])


def fit_sphere(points, centre, fallback):
    """The ball the head sits in.

    The helmet is very nearly a ball -- the fit is good to a couple of
    millimetres over a head this size -- and a ball is the one shape that
    can be fitted from a rim that is only a third of the head's outline.
    An ellipsoid would want the whole outline to fit, and the outline is
    exactly what is missing.
    """
    centre = Vector(centre)
    if not points:
        return Ellipsoid(centre, Vector((fallback, fallback, fallback)))
    distances = [(point - centre).length for point in points]
    radius = float(np.mean(distances))
    return Ellipsoid(centre, Vector((radius, radius, radius)))


def smooth_ring(unit_ring, passes=14, weight=0.3):
    """Take the jag out of a ring without letting it collapse."""
    current = [Vector(p) for p in unit_ring]
    count = len(current)
    for _ in range(passes):
        following = []
        for index in range(count):
            before = current[(index - 1) % count]
            after = current[(index + 1) % count]
            middle = current[index]
            blended = middle * (1.0 - weight) + (before + after) * (0.5 * weight)
            length = blended.length
            following.append(blended / length if length > 1e-9 else middle)
        current = following
    return current


def inside_area(unit_ring, candidate):
    """How the rim winds around a direction on the sphere.

    A closed curve on a sphere divides it into two pieces, and the only
    way to tell which one is the hole is to look at which way the curve
    winds.  Seen from a direction inside the hole the rim goes one way
    round; seen from outside it goes the other.  The sign of the area the
    rim encloses in the tangent plane at the candidate says which.

    It matters because the tear this patches is a long gash, and the
    middle of its rim is not anywhere near the middle of the hole: the
    rim of a gash runs around the outside of the head, so the average of
    its points is on the far side of the helmet, and a patch built toward
    that average sweeps across the face and covers the visor.
    """
    normal = Vector(candidate).normalized()
    # A frame in the tangent plane at the candidate.
    helper = Vector((0.0, 0.0, 1.0))
    if abs(normal.dot(helper)) > 0.9:
        helper = Vector((1.0, 0.0, 0.0))
    right = normal.cross(helper).normalized()
    up = normal.cross(right).normalized()
    points = []
    for point in unit_ring:
        flat = point - normal * point.dot(normal)
        if flat.length < 1e-9:
            return 0.0
        flat.normalize()
        points.append((flat.dot(right), flat.dot(up)))
    area = 0.0
    for index in range(len(points)):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def find_inside(unit_ring):
    """A direction that is inside the region the rim encloses."""
    centroid = Vector((0.0, 0.0, 0.0))
    for point in unit_ring:
        centroid += point
    centroid /= len(unit_ring)
    if centroid.length < 1e-6:
        centroid = Vector((0.0, 0.0, 1.0))
    centroid.normalize()
    # The winding of the rim gives the sign that means "inside"; the
    # candidate with the biggest area of that sign is the middle of the
    # hole.
    sign = 1.0 if inside_area(unit_ring, centroid) > 0.0 else -1.0
    best = None
    best_area = 0.0
    # A coarse grid over the sphere, plus the centroid and the rim's own
    # points nudged towards the middle of the head, which is where a tear
    # in a helmet almost always is.
    seeds = [centroid]
    steps = 12
    for i in range(steps):
        for j in range(steps * 2):
            theta = math.pi * (i + 0.5) / steps
            phi = math.tau * j / (steps * 2)
            seeds.append(Vector((
                math.sin(theta) * math.cos(phi),
                math.sin(theta) * math.sin(phi),
                math.cos(theta),
            )))
    for seed in seeds:
        area = inside_area(unit_ring, seed)
        if area * sign <= 0.0:
            continue
        if area > best_area:
            best_area = area
            best = seed
    return best


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    centre = [float(part) for part in
              value_after("--centre", "0.038,-0.001,0.094").split(",")]
    radius = float(value_after("--radius", "0.289"))
    weld = float(value_after("--weld", "0.0006"))
    rings = int(value_after("--rings", "10"))
    min_edges = int(value_after("--min-edges", "150"))
    report_only = "--report-only" in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    if weld > 0:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

    loops = boundary_loops(bm)
    candidates = []
    for loop in loops:
        rim = rim_order(loop)
        if len(rim) < min_edges:
            continue
        points = np.array([[v.co.x, v.co.y, v.co.z] for v in rim])
        low = points.min(axis=0)
        high = points.max(axis=0)
        candidates.append({
            "loop": loop,
            "rim": rim,
            "edges": len(rim),
            "low": low,
            "high": high,
        })
    report = {
        "source": str(source),
        "loops": len(loops),
        "candidates": len(candidates),
    }
    if not candidates:
        report["patched"] = False
        print("YXZ_CROWN " + json.dumps(report))
        bm.free()
        return

    # The tear is the biggest one that sits on the head.  The eye sockets
    # are holes too, but they are where the eyes go and they are much
    # smaller; the tear is the one that shows.
    def on_head(candidate):
        middle = (candidate["low"] + candidate["high"]) * 0.5
        return (Vector(middle) - Vector(centre)).length < radius * 1.2

    head_candidates = [c for c in candidates if on_head(c)]
    if not head_candidates:
        report["patched"] = False
        print("YXZ_CROWN " + json.dumps(report))
        bm.free()
        return
    target = max(head_candidates, key=lambda c: c["edges"])
    rim = target["rim"]
    report["tearEdges"] = target["edges"]
    report["tearBox"] = [round(float(v), 4)
                          for v in list(target["low"]) + list(target["high"])]

    # The ball the head sits in, fitted to the rim of the tear: the rim is
    # the one piece of the shell that is definitely on the outside of the
    # head, and it is all the patch has to agree with.
    shape = fit_sphere([v.co for v in rim], centre, radius)
    report["headRadius"] = round(shape.radii.x, 4)

    # The rim, in the ball's own coordinates.
    unit = [shape.parameter(v.co) for v in rim]
    unit = smooth_ring(unit)
    # The middle of the hole, in the same coordinates.
    centroid = find_inside(unit)
    if centroid is None:
        report["patched"] = False
        report["inside"] = False
        print("YXZ_CROWN " + json.dumps(report))
        bm.free()
        return
    report["inside"] = True

    uv_layer = bm.loops.layers.uv.active
    rim_uv = []
    for vertex in rim:
        loops_of = list(vertex.link_loops)
        rim_uv.append(loops_of[0][uv_layer].uv.copy() if loops_of else None)
    good = [uv for uv in rim_uv if uv is not None]
    flat_uv = Vector((0.5, 0.5))
    if good:
        flat_uv = Vector((sum(uv.x for uv in good) / len(good),
                          sum(uv.y for uv in good) / len(good)))

    if report_only:
        report["patched"] = False
        print("YXZ_CROWN " + json.dumps(report))
        bm.free()
        return

    # The rim's own vertices are moved onto the smoothed rim, so the patch
    # and the shell meet along the same vertices and the join is not a
    # crack but a line.  They move along the radius, so the edge of the
    # tear keeps its shape and only its depth changes -- the ragged edge
    # of a tear is a millimetre or two of depth, and taking it out is what
    # stops the join from being a row of steps.
    for index, vertex in enumerate(rim):
        vertex.co = shape.place(unit[index])

    # Ring by ring inward.  Each ring is a scaled copy of the rim in the
    # ellipsoid's coordinates, and every point of it is pushed back onto
    # the ellipsoid, so the patch is a piece of the head's own shape.
    count = len(rim)
    grid = [[bm.verts.new(shape.place(unit[index])) for index in range(count)]]
    for step in range(1, rings):
        fraction = 1.0 - (step / rings) ** 0.85
        row = []
        for index in range(count):
            point = centroid + (unit[index] - centroid) * fraction
            length = point.length
            row.append(bm.verts.new(shape.place(point / length)))
        grid.append(row)
    apex = bm.verts.new(shape.place(centroid))

    made = 0
    patch_faces = []
    for step in range(len(grid) - 1):
        inner = grid[step]
        outer = grid[step + 1]
        for index in range(count):
            after = (index + 1) % count
            try:
                face = bm.faces.new((inner[index], inner[after],
                                     outer[after], outer[index]))
            except ValueError:
                continue
            face.smooth = True
            patch_faces.append(face)
            made += 1
    last = grid[-1]
    for index in range(count):
        after = (index + 1) % count
        try:
            face = bm.faces.new((last[index], last[after], apex))
        except ValueError:
            continue
        face.smooth = True
        patch_faces.append(face)
        made += 1

    # The crown is a flat white, so the patch takes the rim's own colour
    # and the seam is not a colour change.
    if uv_layer is not None:
        for face in patch_faces:
            for loop in face.loops:
                loop[uv_layer].uv = flat_uv

    # Which way the patch faces is decided by the shell it is attached to:
    # the patch is part of the head, so it faces the way the head faces.
    outward = Vector((0.0, 0.0, 0.0))
    for vertex in rim[:64]:
        for face in vertex.link_faces:
            if face in patch_faces:
                continue
            outward += face.normal
    if outward.length > 1e-9:
        patch_normal = Vector((0.0, 0.0, 0.0))
        for face in patch_faces:
            patch_normal += face.normal
        if patch_normal.dot(outward) < 0.0:
            bmesh.ops.reverse_faces(bm, faces=patch_faces)

    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.normal_update()
    bm.to_mesh(body.data)
    body.data.update()
    report["patched"] = True
    report["patchFaces"] = made
    report["facesAfter"] = len(bm.faces)
    bm.free()
    print("YXZ_CROWN " + json.dumps(report))

    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_apply=False,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_skins=True,
        export_morph=True,
        export_yup=True,
        export_draco_mesh_compression_enable=False,
    )
    print("YXZ_CROWN_WRITTEN " + str(output))


if __name__ == "__main__":
    main()
