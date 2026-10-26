"""Decide, per pixel, whether the head is see-through or merely mis-shaded.

The other probes answer this question indirectly and disagree with each
other.  `probe_yxz_holes.py` walks the edge graph and reports no boundary
loops, which says the mesh is closed; the unlit render still shows black
in the middle of the face.  Both can be true at once if the black is a
place where the camera sees the *back* of a face that the renderer culls,
and they can also disagree because a graph walk only ever reports loops it
can reach.

So this casts a ray for every pixel of the same orthographic view the audit
renders use, and reports three things per pixel:

   #   a triangle facing the camera -- this is what should be white
   x   a triangle facing away -- geometry is there, the renderer is culling
       it, so this is a winding problem
   .   no triangle at all along the whole ray -- this is a real gap

Usage:
  blender -b -P scripts/probe_yxz_seethrough.py -- \
    --glb <glb> [--center-z 0.28] [--scale 0.55] [--res 220] [--yaw 0]
"""

from __future__ import annotations

import math
import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def drop_stray_objects(scene) -> int:
    """Remove the mesh the glTF importer invents for this file.

    Blender 5.2's glTF importer leaves an `Icosphere` behind for this VRM:
    42 vertices, 80 faces, a unit sphere at the origin, with no material, no
    vertex groups and no parent.  Every mesh the file actually declares has
    all three.  A unit sphere sitting at the origin swallows the whole audit
    view -- every ray hits the sphere, so the character is reported as one
    unbroken shell and the head renders as a ball.

    Returns how many objects were removed, so a caller can notice when the
    thing it measured was not the thing it thought.
    """
    removed = 0
    for obj in list(scene.objects):
        if obj.type != "MESH" or len(obj.data.materials) > 0:
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(data)
        removed += 1
    return removed


def main() -> None:
    # Calibrate before anything is measured.  `BVHTree.FromPolygons` hands
    # back a face normal whose sign is the opposite of what a reader
    # expects, and a test written the other way round reports a perfectly
    # good mesh as 100% inside-out.
    front_is_positive = calibrate()
    glb = value_after("--glb")
    center_z = float(value_after("--center-z", 0.28))
    scale = float(value_after("--scale", 0.55))
    res = int(value_after("--res", 220))
    yaw = math.radians(float(value_after("--yaw", 0.0)))
    pitch = math.radians(float(value_after("--pitch", 0.0)))
    distance = float(value_after("--distance", 2.0))
    centre_arg = value_after("--center")
    centre = (Vector([float(p) for p in centre_arg.split(",")])
              if centre_arg else Vector((0.0, 0.0, center_z)))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene
    stray = drop_stray_objects(scene)
    # Nothing is placed until the view layer has been rebuilt; a depsgraph
    # taken before this still thinks every object is still at the origin,
    # and every ray misses.
    bpy.context.view_layer.update()

    meshes = [o for o in scene.objects if o.type == "MESH"]
    total_faces = sum(len(o.data.polygons) for o in meshes)
    print("YXZ_STRAY_REMOVED " + repr(stray))
    print("YXZ_MESH_NAMES " + repr([
        [o.name, len(o.data.vertices), len(o.data.polygons),
         [round(c, 3) for c in o.location]]
        for o in meshes
    ]))

    # The same camera the audit renders build: orthographic, looking along
    # -Y (or +Y with --flip), +Z up.
    flip = "--flip" in sys.argv
    base = Vector((0.0, 1.0 if flip else -1.0, 0.0))
    turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
    origin = centre + turned * (distance * math.cos(pitch))
    origin.z += distance * math.sin(pitch)
    forward = (centre - origin).normalized()
    right = forward.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(forward).normalized()

    bounds = [obj.matrix_world @ Vector(corner)
              for obj in meshes for corner in obj.bound_box]
    low = [min(v[i] for v in bounds) for i in range(3)]
    high = [max(v[i] for v in bounds) for i in range(3)]
    print("YXZ_BOUNDS " + repr({
        "low": [round(v, 4) for v in low],
        "high": [round(v, 4) for v in high],
    }))

    # A tree per mesh, built from world-space geometry.
    #
    # `Scene.ray_cast` is the obvious way to do this and it does not work:
    # it returns a miss for every ray here, including rays straight down
    # the middle of the head, which is not a fact about the model.  A tree
    # built by hand from the same triangles the renderer draws has no scene
    # state to disagree with.
    trees = []
    for obj in meshes:
        mesh = obj.data
        matrix = obj.matrix_world
        verts = [matrix @ v.co for v in mesh.vertices]
        tris = [list(p.vertices) for p in mesh.polygons]
        trees.append(BVHTree.FromPolygons(verts, tris, all_triangles=True))

    _loc, _nrm, _idx, _dist = trees[0].ray_cast(
        Vector((0.0, -2.0, 0.28)), Vector((0.0, 1.0, 0.0)))
    _all = [v.co for obj in meshes for v in obj.data.vertices]
    print("YXZ_RAY_DEBUG " + repr({
        "trees": len(trees),
        "tree0Verts": len(meshes[0].data.vertices),
        "tree0Faces": len(meshes[0].data.polygons),
        "vertY": [round(min(v.y for v in _all), 4), round(max(v.y for v in _all), 4)],
        "hitY": None if _loc is None else round(_loc.y, 4),
        "origin": [round(c, 4) for c in origin],
        "forward": [round(c, 4) for c in forward],
        "right": [round(c, 4) for c in right],
        "up": [round(c, 4) for c in up],
        "centreRayHit": trees[0].ray_cast(origin, forward)[0] is not None,
    }))
    front = back = miss = 0
    cells = []
    back_sample = []
    # Which mesh each verdict belongs to.
    #
    # A global "38% of the head is back-facing" cannot be acted on.  The same
    # number is either one part inside out or a scatter of slivers across
    # twenty, and those want opposite fixes: the first is a winding pass on
    # one mesh, the second is deleting faces.  So every verdict is filed
    # under the object it came from and reported per object.
    per_object = {}

    def file_under(index: int, kind: str) -> None:
        name = meshes[index].name
        entry = per_object.setdefault(
            name,
            {"faces": len(meshes[index].data.polygons), "front": 0, "back": 0, "miss": 0},
        )
        entry[kind] += 1

    step = scale / res
    # The pixel offset has to ride on top of the distance to the model.
    # Without the `forward * distance` term the target is a fraction of a
    # unit away from the origin and the ray points off at the offset
    # instead of at the head, which misses everything.
    eye = origin + forward * distance
    for iy in range(res):
        row = []
        # Pixel centres, so the count is of pixel centres rather than of
        # grid lines that never land on anything.
        v = (iy + 0.5 - res / 2) * step
        for ix in range(res):
            u = (ix + 0.5 - res / 2) * step
            target = eye + right * u + up * v
            direction = (target - origin).normalized()
            best = None
            for tree in trees:
                loc, normal, _index, distance = tree.ray_cast(origin, direction)
                if loc is not None and (best is None or distance < best[3]):
                    owner = trees.index(tree)
                    best = (loc, normal, _index, distance, owner)
            if best is None:
                miss += 1
                row.append(".")
                if ix == res // 2 and iy == res // 2:
                    print("YXZ_LOOP_DEBUG " + repr({
                        "origin": [round(c, 4) for c in origin],
                        "direction": [round(c, 4) for c in direction],
                        "centreRay": trees[0].ray_cast(origin, direction)[0] is not None,
                        "treesAlive": sum(1 for t in trees if t is not None),
                    }))
                continue
            loc, normal, _index, _distance, owner = best
            # The geometric normal of the triangle against the direction the
            # ray was travelling decides which of the two faces we are on,
            # using the sign the calibration established rather than the one
            # that seems obvious.
            facing = normal.dot(target - loc)
            if (facing >= 0) == front_is_positive:
                front += 1
                row.append("#")
                file_under(owner, "front")
            else:
                back += 1
                row.append("x")
                file_under(owner, "back")
                if len(back_sample) < 8:
                    back_sample.append([meshes[owner].name, [round(c, 4) for c in loc]])
        cells.append(row)

    total = res * res
    print("YXZ_SEETHROUGH " + repr({
        "res": res,
        "objects": len(meshes),
        "faces": total_faces,
        "frontPct": round(front / total * 100, 2),
        "backPct": round(back / total * 100, 2),
        "missPct": round(miss / total * 100, 2),
    }))
    ranked = sorted(per_object.items(), key=lambda kv: -kv[1]["back"])
    print("YXZ_SEETHROUGH_PER_OBJECT " + repr([
        {
            "name": name,
            "meshFaces": entry["faces"],
            "frontPx": entry["front"],
            "backPx": entry["back"],
            "backPctOfWindow": round(entry["back"] / total * 100, 2),
        }
        for name, entry in ranked if entry["front"] or entry["back"]
    ]))
    # Where the corners of the window actually land.  A window that reports
    # solid geometry all the way to its corners is not measuring the head;
    # it is measuring something the audit render never sees.
    corners = {}
    for label, (cx, cy) in {"topLeft": (0, 0), "topRight": (res - 1, 0),
                            "bottomLeft": (0, res - 1),
                            "bottomRight": (res - 1, res - 1),
                            "topMid": (res // 2, 0)}.items():
        u = (cx + 0.5 - res / 2) * step
        v = (cy + 0.5 - res / 2) * step
        direction = (eye + right * u + up * v - origin).normalized()
        best = None
        for index, tree in enumerate(trees):
            loc, _n, _i, distance = tree.ray_cast(origin, direction)
            if loc is not None and (best is None or distance < best[1]):
                best = (index, distance, loc)
        corners[label] = (None if best is None
                          else [meshes[best[0]].name, round(best[1], 3),
                                [round(c, 3) for c in best[2]]])
    print("YXZ_SEETHROUGH_CORNERS " + repr(corners))
    if back_sample:
        print("YXZ_SEETHROUGH_BACK_SAMPLE " + repr(back_sample))
    # A coarse picture, so a black patch can be pointed at without reading
    # a hundred thousand numbers.
    every = max(1, res // 44)
    rows = ["".join(cells[iy][ix] for ix in range(0, res, every))
            for iy in range(0, res, every)]
    print("YXZ_SEETHROUGH_MAP " + repr(rows))

    # The same framing as the audit render, so the two can be put side by
    # side and compared pixel for pixel.  Green is a front face, red is a
    # back face, black is a gap.
    out = value_after("--out")
    if out:
        image = bpy.data.images.new("seethrough", width=res, height=res, alpha=False)
        pixels = [0.0] * (res * res * 4)
        for y in range(res):
            # Image rows run bottom-up, the ray grid runs top-down.
            row = cells[res - 1 - y]
            for x in range(res):
                at = (y * res + x) * 4
                mark = row[x]
                pixels[at] = 0.0 if mark == "." else (0.15 if mark == "#" else 1.0)
                pixels[at + 1] = 1.0 if mark == "#" else (0.15 if mark == "." else 0.0)
                pixels[at + 2] = 0.15 if mark != "." else 0.0
                pixels[at + 3] = 1.0
        image.pixels = pixels
        image.filepath_raw = out
        image.file_format = "PNG"
        image.save()
        print("YXZ_SEETHROUGH_SAVED " + str(out))


def calibrate() -> None:
    """Check the front/back test against a sphere whose answer is known.

    A UV sphere built by Blender has its normals pointing outwards, so a
    ray fired at it from outside must land on a front-facing triangle.
    If this says the sphere is all back-facing then the test is measuring
    the opposite of what it claims and every number below it is upside
    down -- which is a worse outcome than a broken model, because it looks
    like a finding.
    """
    # Built with bmesh and never linked to the scene.  Adding it as an
    # object and deleting it afterwards does not work here: the file that
    # `read_factory_settings` reloads brings the sphere back, and from then
    # on every ray in this probe hits a unit sphere sitting in front of the
    # character and reports the character as one solid unbroken shell.
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    verts = [v.co.copy() for v in bm.verts]
    tris = [[v.index for v in face.verts] for face in bm.faces]
    tree = BVHTree.FromPolygons(verts, tris)
    origin = Vector((0.0, -3.0, 0.0))
    target = Vector((0.0, 0.0, 0.0))
    direction = (target - origin).normalized()
    loc, normal, _index, _distance = tree.ray_cast(origin, direction)
    if loc is None:
        print("YXZ_CALIBRATION " + repr({"hit": False}))
        return True
    sign = 1.0 if normal.dot(target - loc) >= 0 else -1.0
    print("YXZ_CALIBRATION " + repr({
        "hitY": round(loc.y, 4),
        "expectedY": -1.0,
        # A UV sphere's normals point outwards, so the hit from outside is
        # the front face.  Whatever sign this comes out as is the sign the
        # front/back test has to be written with.
        "signForFrontFace": sign,
    }))
    bm.free()
    return sign > 0


if __name__ == "__main__":
    main()
