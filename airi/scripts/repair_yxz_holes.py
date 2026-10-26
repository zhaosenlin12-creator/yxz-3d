"""Close the holes in the scan's shell.

The scan was built to be seen from outside, so where the character folds
-- between the legs, under the pelvis, round the shin -- the surface simply
stops and the shell is left open.  On screen that is the worst fault the
model has: the material is single sided, so an open shell is not a
shading problem but a window, and the background shows through it while
the dark inside of the far wall shows through the rest of it.  A hole in
the shin is a white patch on the leg; an open pelvis is the character
looking at its own navel.

It cannot be repaired by moving anything.  The surface that would close a
hole is not in the file, so the only thing to do is to grow it.

The difficulty is that the scan's surface is cut into pieces.  Every seam
was cut with two vertices where there should be one, so every edge along
every seam is a boundary edge, and a run of boundary edges describes the
whole model rather than the few holes in it.  A fill pass therefore sees
eleven thousand holes and closes none of them.  Welding by position is
what turns that back into a shell: the seam's two vertices become one,
the boundary edges along it stop being boundary, and what is left over is
the handful of real holes the scan never filled in.

The weld is not free.  It merges the surface where the scan's pieces
overlap and it pulls a fringe of slivers out of shape, so the normals are
repaired afterwards and the result is measured rather than assumed: the
picture this produces is compared against the picture the model had before.

Newly grown faces have no place in the atlas, and a face that samples the
wrong corner of it is worse than a hole.  So every new vertex takes the
coordinates of the nearest vertex that already had some.  The holes are
small, the surface around them is continuous, and a coordinate from a few
thousandths away lands on the right texel.

Usage:
  blender -b -P scripts/repair_yxz_holes.py -- \
    --source <glb> --output <glb> [--weld 0.0006] [--max-hole 0.02]
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


def boxes_after(name):
    """The boxes the repair is not allowed to touch."""
    boxes = []
    index = 0
    while True:
        flag = "%s%d" % (name, index)
        if flag not in sys.argv:
            break
        index += 1
        raw = sys.argv[sys.argv.index(flag) + 1]
        values = [float(piece) for piece in raw.split(",")]
        boxes.append(tuple(values))
    return boxes


PROTECTED = []


def in_protected(points, box):
    """Whether a run of boundary lies inside a box that is off limits."""
    x0, y0, z0, x1, y1, z1 = box
    low = points.min(axis=0)
    high = points.max(axis=0)
    return bool(
        low[0] >= x0 and high[0] <= x1
        and low[1] >= y0 and high[1] <= y1
        and low[2] >= z0 and high[2] <= z1
    )


def boundary_loops(bm):
    """The runs of edges that have a face on only one side."""
    loose = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    # The walk below starts from an arbitrary run and takes whichever run it
    # finds next, so the order it visits them in has to be decided by the
    # geometry and not by the order the edges happen to sit in memory.  Two
    # builds of the same model were coming out with a different number of
    # holes -- one closed the tear on the visor, the next did not -- purely
    # because a set of bmesh edges iterates differently from one run to the
    # next.  Sorting by where the edge is makes the same model give the same
    # answer every time.
    def sort_key(edge):
        return (tuple(round(c, 7) for c in edge.verts[0].co),
                tuple(round(c, 7) for c in edge.verts[1].co))

    loose.sort(key=sort_key)
    adjacency = {}
    for edge in loose:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    for edges in adjacency.values():
        edges.sort(key=sort_key)

    unvisited = {}
    for edge in loose:
        unvisited[sort_key(edge)] = edge
    loops = []
    while unvisited:
        seed = unvisited.pop(min(unvisited))
        loop = [seed]
        # The walk follows the run from vertex to vertex until it arrives
        # back where it started, which is what makes a run a loop rather
        # than a list, and then keeps going if the boundary ran on into a
        # second loop that shared the starting vertex.
        start = seed.verts[0]
        current = seed.verts[1]
        while True:
            following = None
            for edge in adjacency.get(current, ()):
                if sort_key(edge) in unvisited:
                    following = edge
                    break
            if following is None:
                break
            del unvisited[sort_key(following)]
            loop.append(following)
            head, tail = following.verts
            current = tail if head is current else head
            if current is start:
                break
        loops.append(loop)
    return loops


def loop_is_closed(loop):
    """Whether a run of boundary edges joins back on itself."""
    if not loop:
        return False
    count = {}
    for edge in loop:
        for vertex in edge.verts:
            count[vertex.index] = count.get(vertex.index, 0) + 1
    return all(hits % 2 == 0 for hits in count.values())


def loop_span(loop):
    """The widest gap in a run, which is what says how big the hole is."""
    if not loop:
        return 0.0
    return max((edge.verts[0].co - edge.verts[1].co).length for edge in loop)


def grow_uv_table(bm):
    """Where every vertex that already had a place in the atlas sits."""
    uv_layer = bm.loops.layers.uv.active
    table = KDTree(len(bm.verts))
    coords = np.empty(len(bm.verts) * 3, dtype=np.float64)
    bm.verts.ensure_lookup_table()
    for vertex in bm.verts:
        table.insert(vertex.co, vertex.index)
    table.balance()

    known = {}
    for face in bm.faces:
        for loop in face.loops:
            known[loop.vert.index] = loop[uv_layer].uv
    return table, known


def conform_patches(bm, grown, loops, fresh_from, table, known, report,
                    cuts=3):
    """Lay the grown faces back onto the surface they were torn from.

    A hole is filled with a single face whose corners are all on the rim,
    so what fills it is the flat lid of a bowl: across a tear the width of
    a cheek the lid cuts the corner and sits *inside* the visor it is
    meant to be flush with.  Nothing about it is visible as a mistake --
    it is in shadow, which is why a repaired tear came out looking like a
    dark hole that had simply moved.

    So the face is cut up and the new vertices inside it are put back onto
    the surface around it.  A tear is a hole in a smooth surface, so the
    rim of the tear describes the surface around it well enough to say
    what the missing middle would have been, and the patch becomes that
    surface rather than the flat lid of a bowl.
    """
    if not grown:
        return {"subdivided": 0, "conformed": 0}

    # The filled face is cut into triangles first, because a single face
    # with a hundred corners on it has no inside to cut, and then the cuts
    # are cut again, which is what puts vertices inside the patch at all.
    result = bmesh.ops.triangulate(bm, faces=list(grown))
    patch = list(result.get("faces", grown))
    report["patchFaces"] = len(patch)

    inner_edges = {edge for face in patch for edge in face.edges
              if len(edge.link_faces) > 1}
    if inner_edges:
        bmesh.ops.subdivide_edges(bm, edges=list(inner_edges), cuts=cuts,
                                  use_grid_fill=True)
    bm.verts.ensure_lookup_table()
    # bmesh keeps the vertices it already had at the indices it gave them
    # and appends every new one after them, so the corners the cutting
    # added are exactly those past the count taken before any of it ran.
    # Comparing the objects themselves does not work: bmesh moves its
    # elements around as it works and half of them come back as different
    # objects, and the tag a new vertex is born with is inherited by the
    # vertices a cut makes out of it.
    fresh = [vertex for vertex in bm.verts if vertex.index >= fresh_from]
    report["freshVertices"] = len(fresh)
    uv_layer = bm.loops.layers.uv.active

    # Every vertex the cutting added sits on a straight chord between two
    # points on the rim, which is inside the surface the patch is meant to
    # be flush with.  Each one is put back onto that surface by a quadratic
    # fitted through the rim itself, taken in the rim's own frame so that
    # "flush" means flush with the visor rather than with the world.  A
    # plane through the rim would still cut the corner, and the corner is
    # the whole of the fault.
    moved = 0
    for loop in loops:
        surface = _surface_through(loop)
        if surface is None:
            report.setdefault("refusedPatches", 0)
            report["refusedPatches"] += 1
            continue
        project, place, hull = surface
        # The atlas is the one thing a patch cannot invent.  This tear runs
        # across the boundary between two parts of it -- it starts on the
        # visor and finishes on the white of the cheek -- so a corner that
        # takes its colour from the nearest vertex comes out part dark navy
        # and part white with a hard seam between them, and a visor with a
        # hard seam across it reads as cracked rather than as repaired.
        #
        # The rim is the only part of the patch whose place in the atlas is
        # known and known to be right, so every new corner takes a weighted
        # average of the rim corners nearest to it.  The weights fall off
        # with distance, so the patch fades from visor to cheek the way the
        # surface round the tear already does.
        rim_verts = []
        for edge in loop:
            rim_verts.append(edge.verts[0])
            rim_verts.append(edge.verts[1])
        rim_uv = []
        rim_tree = KDTree(len(rim_verts))
        for position, vertex in enumerate(rim_verts):
            rim_tree.insert(vertex.co, position)
            _, index, _ = table.find(vertex.co)
            rim_uv.append(known.get(index))
        rim_tree.balance()
        for vertex in fresh:
            local = project(vertex.co)
            if local is None or not _within(local, hull):
                continue
            placed = place(local)
            if placed is None:
                continue
            if (Vector(placed) - vertex.co).length > 1e-7:
                moved += 1
            vertex.co = Vector(placed)
            weight = 0.0
            summed = [0.0, 0.0]
            for _, position, distance in rim_tree.find_n(vertex.co, 8):
                uv = rim_uv[position]
                if uv is None:
                    continue
                share = 1.0 / (distance * distance + 1e-9)
                summed[0] += uv.x * share
                summed[1] += uv.y * share
                weight += share
            if weight > 0.0:
                for loop_index in _loops_of(vertex):
                    loop_index[uv_layer].uv = (summed[0] / weight,
                                               summed[1] / weight)
    report["conformedVertices"] = moved
    return report


def _loops_of(vertex):
    return [item for edge in vertex.link_edges for item in edge.link_loops]


def rim_order(loop):
    """The vertices of a boundary run in the order the run walks them."""
    walk = []
    for edge in loop:
        head = walk[-1] if walk else edge.verts[0]
        walk.append(edge.verts[1] if edge.verts[0] is head else edge.verts[0])
    if len(walk) > 1 and walk[0] == walk[-1]:
        walk.pop()
    return walk


def cap_open_boundaries(bm, open_loops, table, known, report,
                        min_edges=10, max_span=0.14):
    """Close the runs of boundary that never join back on themselves.

    These are not tears but places the scan stopped: the underside of the
    pelvis, where the two legs are separate tubes and nothing was ever
    generated between them.  On screen that is the character with its
    middle missing -- the background shows straight through the gap between
    the legs and the dark inside of the far wall shows through the rest of
    it, which is the single most broken thing about the model.

    A fill cannot take an open run, because there is nothing for it to
    close, so the run is capped by hand: the surface is fitted through the
    run the same way it is fitted for a tear, and the fitted middle is
    fanned out to the rim.  The rim is not moved, so the cap meets the
    surface exactly where the scan stopped.

    The rim has to be worth capping.  A run of a few edges is a nick and
    capping it would leave a lump, and a run that reaches right across the
    character is an opening the model is meant to have -- the top of the
    helmet and the sole of a foot both stop at nothing -- so both are
    refused rather than guessed at.
    """
    report["capCandidates"] = 0
    report["caps"] = 0
    for loop in open_loops:
        if len(loop) < min_edges or loop_span(loop) > max_span:
            continue
        report["capCandidates"] += 1
        surface = _surface_through(loop)
        if surface is None:
            continue
        project, place, _ = surface
        rim = rim_order(loop)
        if len(rim) < min_edges:
            continue

        centroid = Vector((0.0, 0.0, 0.0))
        for vertex in rim:
            centroid += vertex.co
        centroid /= len(rim)
        local = project(centroid)
        if local is None:
            continue
        middle = place(local)
        if middle is None:
            continue
        centre = bm.verts.new(middle)

        faces = []
        for index in range(len(rim)):
            faces.append(bm.faces.new((rim[index],
                                       rim[(index + 1) % len(rim)],
                                       centre)))
        # Which way a cap faces is decided by the order the rim was walked
        # in, and a cap that faces inwards is culled by the single sided
        # material and leaves the model exactly as open as it was.  The
        # surface the rim belongs to says which way is out.
        outward = Vector((0.0, 0.0, 0.0))
        for face in faces:
            outward += face.normal
        inward = Vector((0.0, 0.0, 0.0))
        for vertex in rim:
            for face in vertex.link_faces:
                if face in faces:
                    continue
                inward += face.normal
        if outward.length > 1e-9 and outward.dot(inward) < 0.0:
            for face in faces:
                face.normal_flip()
        report["caps"] += 1
        report.setdefault("capSpans", []).append(round(loop_span(loop), 4))

        # The new corner in the middle of the cap has no place in the atlas,
        # so it is given the middle of the rim's own.  A cap spans a flat
        # colour of the model and the average of the rim is that colour.
        uv_layer = bm.loops.layers.uv.active
        _, index, _ = table.find(centre.co)
        if index in known:
            for face in faces:
                for loop_index in face.loops:
                    if loop_index.vert is centre:
                        loop_index[uv_layer].uv = known[index]
    return report


def _surface_through(loop):
    """A smooth surface fitted through the rim of a tear.

    The two directions the rim spreads furthest along are used as its own
    axes and the direction it is thinnest in is taken as the surface's
    normal.  Over those two directions the surface is fitted as a
    quadratic, which is what a visor or a thigh needs and no more.  The
    fit is refused when the rim is nearly flat, because a flat ring says
    nothing about which way the surface goes through it and a guess would
    be worse than the chord.
    """
    rim = [edge.verts[0] for edge in loop]
    rim = rim + [edge.verts[1] for edge in loop]
    if len(rim) < 12:
        return None
    points = np.array([[c for c in vertex.co] for vertex in rim])
    centre = points.mean(axis=0)
    centred = points - centre
    _, singular, basis = np.linalg.svd(centred, full_matrices=False)
    if singular[-1] > 0.75 * singular[0]:
        return None
    first, second, normal = basis[0], basis[1], basis[2]

    local = centred @ np.stack([first, second, normal], axis=1)
    u = local[:, 0]
    v = local[:, 1]
    design = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], axis=1)
    solution = np.linalg.lstsq(design, local[:, 2], rcond=None)[0]

    def project(point):
        offset = np.array([c for c in point]) - centre
        return float(offset @ first), float(offset @ second)

    def place(local):
        a, b = local
        depth = (solution[0] + solution[1] * a + solution[2] * b
                 + solution[3] * a * a + solution[4] * a * b
                 + solution[5] * b * b)
        return centre + first * a + second * b + normal * depth

    hull = _hull([project(vertex.co) for vertex in rim])
    return project, place, hull


def _hull(points):
    """The convex hull of a scatter of points in the surface's own plane."""
    unique = sorted(set(points))
    if len(unique) < 3:
        return []

    def cross(origin, a, b):
        return ((a[0] - origin[0]) * (b[1] - origin[1])
                - (a[1] - origin[1]) * (b[0] - origin[0]))

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _within(point, hull):
    """Whether a point is inside a convex polygon, its own edge aside.

    The rim of the tear lies on the hull by construction, and moving it
    would tear the patch away from the surface it is repairing, so a point
    on the boundary counts as outside and is left where it is.
    """
    if not hull:
        return False
    inside = False
    count = len(hull)
    for index in range(count):
        a = hull[index]
        b = hull[(index + 1) % count]
        if ((a[1] > point[1]) != (b[1] > point[1])):
            crossing = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < crossing:
                inside = not inside
    if not inside:
        return False
    for index in range(count):
        a = hull[index]
        b = hull[(index + 1) % count]
        edge = ((b[0] - a[0]) * (point[1] - a[1])
                - (b[1] - a[1]) * (point[0] - a[0]))
        if abs(edge) < 1e-12:
            return False
    return True


def fill_holes(mesh, weld=0.0006, max_hole=0.02, max_loop_edges=600,
                protect_edges=0):
    """Weld the seams shut and grow the surface over the holes."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    report = {
        "faces_before": len(bm.faces),
        "verts_before": len(bm.verts),
    }

    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    bm.faces.ensure_lookup_table()
    report["faces_after_weld"] = len(bm.faces)

    loops = boundary_loops(bm)
    report["loops"] = len(loops)
    open_loops = [loop for loop in loops if not loop_is_closed(loop)]
    closed_loops = [loop for loop in loops if loop_is_closed(loop)]
    report["closedLoops"] = len(closed_loops)
    report["openLoops"] = len(open_loops)

    # Some parts of the model must be left alone.
    #
    # The head is a dome of the character's own making, and the scan
    # caught it as a dome with a tear in it -- a tear with five hundred
    # edges around it, which is what a dome looks like when the seam
    # that was cut around it was never closed.  Closing that tear is
    # exactly what this script is for, and it is exactly what ruins the
    # head: the tear is capped with a fan of five hundred triangles
    # running to a single point, and the point is placed by a fit
    # through a rim that is not a circle, so the fan comes out as a
    # hedgehog of needles standing off the crown of the helmet.
    #
    # The head does not need closing.  The tear is at the top, it is
    # not visible from anywhere the character is seen from, and the
    # shell behind it is already whole.  So the head is put outside the
    # reach of the repair, and the repair is left to do the job it is
    # good at, which is the open shell under the pelvis and between the
    # legs.
    protected = []
    for loop in loops:
        points = np.array([[c for vertex in edge.verts for c in vertex.co]
                           for edge in loop])
        if not any(in_protected(points, box) for box in PROTECTED):
            continue
        # A protected box keeps the big tears out of the repair, but it
        # must not keep the little ones out with them.
        #
        # The helmet is torn along the seam that was cut around the
        # crown, and that tear is five hundred edges long.  Capping it
        # fills the helmet with a fan of needles standing off the top of
        # the head, so it is left alone.  But the same helmet is peppered
        # with holes a few edges across -- the dust that was taken off
        # the surface left a hole where each piece of it was -- and
        # those are exactly what the repair is for.  They are small, so
        # a box can keep the tear out and let them in at the same time.
        if protect_edges <= 0 or len(loop) > protect_edges:
            protected.append(loop)
    if protected:
        keep = set(id(loop) for loop in protected)
        open_loops = [loop for loop in open_loops if id(loop) not in keep]
        closed_loops = [loop for loop in closed_loops if id(loop) not in keep]
    report["protectedLoops"] = len(protected)

    # Every run is measured and reported, because the difference between a
    # tear worth closing and a boundary the model is supposed to have --
    # the underside of a foot, the crown of the helmet -- is the size of it
    # and where it is, and that is only knowable by looking.
    measured = []
    for loop in loops:
        points = np.array([[c for vertex in edge.verts for c in vertex.co]
                           for edge in loop])
        measured.append({
            "edges": len(loop),
            "span": round(loop_span(loop), 4),
            "closed": loop_is_closed(loop),
            "low": [round(float(c), 3) for c in points.min(axis=0)],
            "high": [round(float(c), 3) for c in points.max(axis=0)],
        })
    measured.sort(key=lambda entry: (-entry["edges"], -entry["span"]))
    for entry in measured[:24]:
        print("YXZ_LOOP " + json.dumps(entry))
    report["biggest"] = measured[:12]

    loops_out = value_after("--loops-out")
    if loops_out:
        with open(loops_out, "w", encoding="utf-8") as handle:
            json.dump(measured, handle)

    table, known = grow_uv_table(bm)
    original = list(bm.verts)
    for vertex in original:
        vertex.tag = True
    fresh_from = len(original)

    # Which way the surface around a tear is facing, worked out before
    # anything is grown.  A shell with a hole in it is not closed, so there
    # is no inside and no outside and Blender's own winding pass has nothing
    # to go on: it can only guess, and a guess that comes out facing inwards
    # is culled by the single sided material, so the hole is still a hole and
    # now shows the inside of the character's own head.
    original_normals = {}
    for face in bm.faces:
        normal = face.normal
        if normal.length < 1e-9:
            continue
        for vertex in face.verts:
            current = original_normals.get(vertex.index)
            if current is None:
                original_normals[vertex.index] = normal.copy()
            else:
                current += normal
    for normal in original_normals.values():
        if normal.length > 1e-9:
            normal.normalize()

    # The seams have just been welded, so every loop left over is a hole the
    # scan never covered.  The ones that reach most of the way across the
    # character are not holes -- the character is not a closed balloon, and
    # the bottom of the feet and the top of the helmet are meant to be open
    # -- so a loop is only filled when it is small enough to be a tear.
    #
    # How many edges a loop has is the second guard, and it is the one that
    # matters.  A tear of a dozen edges is a hole the scan left in the
    # surface, and capping it is what the repair is for.  A tear of a
    # thousand edges is not a hole: it is the seam that was cut around the
    # crown of the helmet, and capping it fills the helmet with a fan of
    # needles standing off the top of the head.  The size of the span
    # cannot tell the two apart -- a tear that follows a seam right across
    # the crown of the head is no wider than a tear in the middle of the
    # visor -- but the number of edges can, so both are used.
    fillable = []
    for loop in closed_loops:
        span = loop_span(loop)
        if span <= max_hole and len(loop) <= max_loop_edges:
            fillable.append((span, loop))
    report["fillableLoops"] = len(fillable)
    report["refusedLoops"] = len(closed_loops) - len(fillable)

    if not fillable:
        bm.free()
        return report

    report["filledSpans"] = [
        round(span, 4)
        for span, _ in sorted(fillable, key=lambda item: (item[0], len(item[1])), reverse=True)[:20]
    ]

    existing = set(bm.faces)
    result = bmesh.ops.holes_fill(bm, edges=[edge for _, loop in fillable
                                             for edge in loop],
                                  sides=0)
    grown = [face for face in result.get("faces", []) if face not in existing]
    report["grownFaces"] = len(grown)

    # Each new face is turned to agree with the surface it is growing out
    # of, which is the only direction that is actually known here.
    flipped = 0
    for face in grown:
        normal = face.normal
        if normal.length < 1e-9:
            continue
        agree = 0.0
        for vertex in face.verts:
            _, index, _ = table.find(vertex.co)
            neighbour = original_normals.get(index)
            if neighbour is not None:
                agree += normal.dot(neighbour)
        if agree < 0.0:
            face.normal_flip()
            flipped += 1
    report["flippedFaces"] = flipped
    bm.normal_update()

    # Cutting the patch up is what gives it an inside, and an inside that
    # follows the visor rather than cutting across it.
    conform_patches(bm, grown, [loop for _, loop in fillable], fresh_from,
                    table, known, report, cuts=3)

    cap_open_boundaries(bm, open_loops, table, known, report)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    report["faces_after_fill"] = len(mesh.polygons)
    return report


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    weld = float(value_after("--weld", 0.0006))
    max_hole = float(value_after("--max-hole", 0.02))
    max_loop_edges = int(value_after("--max-loop-edges", 600))
    protect_edges = int(value_after("--protect-edges", 0))
    global PROTECTED
    PROTECTED = boxes_after("--protect")
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    report = fill_holes(body.data, weld=weld, max_hole=max_hole,
                        max_loop_edges=max_loop_edges,
                        protect_edges=protect_edges)
    report["source"] = str(source)
    report["output"] = str(output)

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
    print("YXZ_HOLES " + json.dumps(report))


if __name__ == "__main__":
    main()
