"""List every place the shell is still open, and how big it is.

The repair pass refuses an opening it cannot judge, so a boot that is open
from the ankle to the sole survives the build untouched.  This walks the
 welded mesh and prints each boundary run with the box it covers, so the
 openings can be matched to what is on screen.

Usage: blender -b -P scripts/probe_yxz_openings.py -- <glb> [--weld 0.0006]
"""

from __future__ import annotations

import json
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from repair_yxz_holes import boundary_loops, loop_is_closed, loop_span, rim_order


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main():
    source = value_after("--source")
    weld = float(value_after("--weld", "0.0006"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    bm = bmesh.new()
    bm.from_mesh(bpy.data.objects[0].data)
    bm.verts.ensure_lookup_table()
    if weld > 0:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

    loops = boundary_loops(bm)
    rows = []
    for loop in loops:
        rim = rim_order(loop)
        if len(rim) < 3:
            continue
        coords = [v.co for v in rim]
        low = [round(min(c[i] for c in coords), 4) for i in range(3)]
        high = [round(max(c[i] for c in coords), 4) for i in range(3)]
        centre = [round(sum(c[i] for c in coords) / len(coords), 4)
                  for i in range(3)]
        rows.append({
            "closed": loop_is_closed(loop),
            "edges": len(loop),
            "verts": len(rim),
            "span": round(loop_span(loop), 4),
            "centre": centre,
            "min": low,
            "max": high,
        })
    rows.sort(key=lambda row: -row["span"])
    print("OPENINGS " + json.dumps({"total": len(rows), "rows": rows}))
    bm.free()


main()
