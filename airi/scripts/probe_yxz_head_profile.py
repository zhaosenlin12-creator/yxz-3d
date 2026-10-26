"""The head's own surface, measured along rays from the middle of it.

Everything that has to be put back on the head -- the crown, the star,
the rim the dome sits on -- is a question of how far out the helmet
is in each direction.  A radius measured from the middle of the head
answers it, but a radius measured as a sphere is wrong here: the
helmet is a wide flattened dome, so the distance from the middle
varies with the direction in a way a single number cannot carry.

So this fires a ray out from the middle of the head in each direction
and reports where it hits, which is the surface itself, measured.

Usage:
  blender -b -P scripts/probe_yxz_head_profile.py -- --source <glb> \
    [--elevations 10,20,30,40,50,60,70,80] [--bearings 0,30,60,90,120,150,180,210,240,270,300,330]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = Path(value_after("--source"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    elevations = [float(v) for v in
                  value_after("--elevations", "10,20,30,40,50,60,70,80").split(",")]
    bearings = [float(v) for v in
                 value_after("--bearings", "0,30,60,90,120,150,180,210,240,270,300,330").split(",")]
    limit = float(value_after("--limit", "0.42"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)

    rows = []
    for bearing in bearings:
        for elevation in elevations:
            phi = math.radians(bearing)
            theta = math.radians(elevation)
            direction = Vector((math.cos(theta) * math.cos(phi),
                                math.cos(theta) * math.sin(phi),
                                math.sin(theta)))
            hits = []
            origin = centre.copy()
            for _ in range(12):
                location, _, _, _ = tree.ray_cast(origin, direction, limit)
                if location is None:
                    break
                distance = (location - centre).length
                hits.append(round(distance, 4))
                origin = location + direction * 0.0015
            rows.append({
                "bearing": bearing,
                "elevation": elevation,
                "hits": hits,
            })

    print("YXZ_HEAD_PROFILE " + json.dumps(rows))
    bm.free()


if __name__ == "__main__":
    main()
