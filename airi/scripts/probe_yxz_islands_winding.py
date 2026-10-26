"""Which connected piece of the shell is turned inside out.

The raycast says roughly seven per cent of the surface the camera can see
is pointing away from it, so a patch of the character is being culled and
reads as a hole.  Whether a patch can be flipped on its own depends on
what it is attached to, so the mesh is cut into connected pieces and each
one is measured: how big it is, which way its volume runs, and where it
sits on the body.

Usage:
  blender -b -P scripts/probe_yxz_islands_winding.py -- <glb> [--weld 0.0006]
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


def signed_volume(bm):
    """Positive when the faces of a closed shell run anticlockwise seen
    from outside, which is the winding a renderer draws."""
    total = 0.0
    for face in bm.faces:
        a, b, c = (v.co for v in face.verts)
        total += a.dot(b.cross(c)) / 6.0
    return total


def main():
    source = value_after("--source")
    weld = float(value_after("--weld", "0.0006"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    low = Vector((1e9, 1e9, 1e9))
    high = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], world[axis])
                high[axis] = max(high[axis], world[axis])

    rows = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        if weld > 0:
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
            bm.edges.ensure_lookup_table()

        seen = set()
        for vertex in bm.verts:
            if vertex.index in seen or not vertex.link_faces:
                continue
            stack = [vertex]
            piece = []
            while stack:
                current = stack.pop()
                if current.index in seen:
                    continue
                seen.add(current.index)
                piece.append(current)
                for edge in current.link_edges:
                    for other in edge.verts:
                        if other.index not in seen:
                            stack.append(other)
            sub = bmesh.new()
            made = {}
            for item in piece:
                made[item.index] = sub.verts.new(item.co.copy())
            for face in bm.faces:
                if all(v.index in made for v in face.verts):
                    corners = [made[v.index] for v in face.verts]
                    try:
                        sub.faces.new(corners)
                    except ValueError:
                        pass
            volume = signed_volume(sub)
            area = sum(f.calc_area() for f in sub.faces)
            coords = [v.co for v in piece]
            centre = [round(sum(c[i] for c in coords) / len(coords), 3)
                      for i in range(3)]
            box_low = [round(min(c[i] for c in coords), 3) for i in range(3)]
            box_high = [round(max(c[i] for c in coords), 3) for i in range(3)]
            sub.free()
            rows.append({"verts": len(piece), "area": round(area, 5),
                         "volume": round(volume, 6), "centre": centre,
                         "min": box_low, "max": box_high})
        bm.free()
    rows.sort(key=lambda row: -row["area"])
    print("ISLANDS " + json.dumps({"total": len(rows), "rows": rows[:40]}))


main()
