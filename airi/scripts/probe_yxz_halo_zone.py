"""
 * Measure where the scan's broken halo is, in the halo's own geometry.
 *
 * The halo is a ring: a circle of a given radius drawn in a plane that is
 * tilted back off the crown.  Anything that is part of that ring is a
 * certain distance from the ring's axis and very close to the ring's
 * plane, and the helmet is nowhere near that -- the crown sits on the
 * axis, and the ear cups are far off it.
 *
 * So the halo's remains are found by geometry rather than by colour.
 * Colour was how they used to be found, and it was why they survived:
 * the test only recognised the halo's cyan, and the pieces that were
 * left over were the dark navy ones.
 *
 * This prints, for every shell that is not the body, how far it is from
 * the ring's axis and how far it is from the ring's plane.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_halo_zone.py -- --glb <glb>
 """

from __future__ import annotations

import json
import math
import sys

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])


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


def main():
    source = value_after("--glb")
    from build_yxz_halo import RING_COLOUR  # noqa: F401  (path check)
    from rebuild_yxz_halo import CENTRE, RADIUS, TILT_DEGREES

    tilt = math.radians(TILT_DEGREES)
    normal = Vector((0.0, math.sin(tilt), math.cos(tilt))).normalized()
    axis_a = Vector((1.0, 0.0, 0.0))
    axis_a = (axis_a - normal * axis_a.dot(normal)).normalized()
    axis_b = normal.cross(axis_a)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)
    body_group = max(groups, key=len)

    in_band = 0
    in_band_faces = 0
    for number, group in enumerate(groups):
        if group is body_group:
            continue
        radii = []
        heights = []
        for face in group:
            for vert in face.verts:
                offset = vert.co - CENTRE
                radii.append(math.hypot(offset.dot(axis_a), offset.dot(axis_b)))
                heights.append(offset.dot(normal))
        record = {
            "id": number,
            "faces": len(group),
            "rMin": round(min(radii), 4),
            "rMax": round(max(radii), 4),
            "hMin": round(min(heights), 4),
            "hMax": round(max(heights), 4),
            "zMin": round(min(v.co.z for f in group for v in f.verts), 4),
            "zMax": round(max(v.co.z for f in group for v in f.verts), 4),
        }
        if record["rMax"] > 0.12 and record["rMin"] < 0.30 and abs(record["hMax"]) < 0.08:
            in_band += 1
            in_band_faces += len(group)
        print("YXZ_ZONE " + json.dumps(record))
    print("YXZ_ZONE_SUMMARY %s" % json.dumps({
        "ringRadius": RADIUS,
        "inBand": in_band,
        "inBandFaces": in_band_faces,
        "totalShells": len(groups) - 1,
    }))
    bm.free()


main()
