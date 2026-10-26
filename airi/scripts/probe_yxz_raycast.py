"""Ask the renderer the question the screen is already answering.

The welded shell has only seven small tears in it, yet the boots read as
open cages.  A surface that is present but turned the wrong way is culled,
which looks exactly like a hole and is not one, so it never reaches the
repair pass.  The difference is settled by casting a ray the way the
camera casts it and looking at which way the face it lands on is pointing:
away from the ray is drawn, back toward it is thrown away.

Usage:
  blender -b -P scripts/probe_yxz_raycast.py -- <glb> [--step 0.004]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

import bpy
import numpy as np
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def ray_hit(scene, depsgraph, origin, direction):
    result = scene.ray_cast(depsgraph, origin, direction)
    return result[0], result[2]


def main():
    source = value_after("--source")
    step = float(value_after("--step", "0.004"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    corner_low = Vector((1e9, 1e9, 1e9))
    corner_high = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                corner_low[axis] = min(corner_low[axis], world[axis])
                corner_high[axis] = max(corner_high[axis], world[axis])
    print("BOUNDS " + json.dumps({"min": list(corner_low),
                                  "max": list(corner_high)}))

    # The body frame faces +X, so the camera sits far out on +X and looks
    # back along -X.
    eye = Vector((corner_high.x + 2.0, 0.0, 0.0))
    direction = Vector((-1.0, 0.0, 0.0))

    grid_y = np.arange(corner_low.y, corner_high.y + step, step)
    grid_z = np.arange(corner_low.z, corner_high.z + step, step)
    cell = 0.02
    tally = defaultdict(lambda: {"front": 0, "back": 0, "miss": 0})
    for z in grid_z:
        for y in grid_y:
            origin = Vector((eye.x, float(y), float(z)))
            hit, normal = ray_hit(scene, depsgraph, origin, direction)
            key = (int((y - corner_low.y) / cell), int((z - corner_low.z) / cell))
            if not hit:
                tally[key]["miss"] += 1
            elif normal.dot(direction) < 0.0:
                tally[key]["front"] += 1
            else:
                tally[key]["back"] += 1

    rows = []
    front_total = 0
    back_total = 0
    for key, counts in tally.items():
        front_total += counts["front"]
        back_total += counts["back"]
        if counts["back"] == 0:
            continue
        rows.append({
            "y": round(corner_low.y + (key[0] + 0.5) * cell, 3),
            "z": round(corner_low.z + (key[1] + 0.5) * cell, 3),
            "front": counts["front"],
            "back": counts["back"],
            "miss": counts["miss"],
        })
    rows.sort(key=lambda row: (row["z"], row["y"]))
    print("RAYCAST " + json.dumps({"front": front_total, "back": back_total,
                                   "rows": rows}))


main()
