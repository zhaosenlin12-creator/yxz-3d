"""Find the sheets of the scan that are lying on top of the character.

Two faults left on the model are the same fault.  A strip of shell along
the jaw, and a few pencilled lines across the crown of the helmet, are
both places where the scan folded a piece of surface back over itself and
left it resting there.  The piece under it is intact; the piece on top is
the duplicate, and it is what draws the line.

Colour cannot find them and neither can position -- a fold lies *on* the
surface rather than beside it, and it is painted the same white as what it
lies on.  What does separate them is depth.  A face on the outside of the
character fires a ray inwards and it travels the whole way through the
body before it finds anything.  A face lying on top of the surface finds
the surface it is lying on almost immediately, a fraction of a millimetre
away, because that surface is right there under it.

So every face is measured that way and the ones that find something too
close are grouped into the sheets they belong to, and the sheets are
printed with the box they cover so they can be matched to what is on
screen.  Nothing is removed here.

Usage:
  blender -b -P scripts/probe_yxz_laps.py -- --glb <glb> [--near 0.004]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict, deque

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main():
    source = value_after("--glb")
    near = float(value_after("--near", "0.004"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        tree = BVHTree.FromBMesh(bm, epsilon=0.0)

        # A face that belongs to the outside of the character has nothing
        # within a few millimetres of it that is not part of the same
        # continuous surface.  A face that is lying on top of the character
        # does: the surface it is lying on is right underneath it.  So the
        # question is not which way a ray goes but whether there is a second
        # surface in the neighbourhood that shares no vertex with this one.
        faces_of_vertex = defaultdict(list)
        for face in bm.faces:
            for vertex in face.verts:
                faces_of_vertex[vertex.index].append(face.index)

        neighbours = {}
        for face in bm.faces:
            shared = set()
            for vertex in face.verts:
                shared.update(faces_of_vertex[vertex.index])
            shared.discard(face.index)
            neighbours[face.index] = shared

        # Distance alone is not enough to tell a fold from the scan's own
        # seams: a shell that was cut and rejoined has faces that share no
        # vertex and yet lie right next to each other.  What separates them
        # is which way the surface under the face is pointing.  A face that
        # continues the surface has neighbours facing the same way; a face
        # that has been folded back over has the surface it was folded onto
        # facing back at it, which is the one thing a continuous surface
        # never does.
        flagged = set()
        gaps = {}
        for face in bm.faces:
            centre = face.calc_center_median()
            for _, other_normal, index, distance in tree.find_nearest_range(
                    centre, near):
                if index == face.index or index in neighbours[face.index]:
                    continue
                if other_normal.dot(face.normal) > -0.2:
                    continue
                flagged.add(face.index)
                gaps[face.index] = distance
                break

        by_edge = defaultdict(list)
        for face in bm.faces:
            keys = [v.index for v in sorted(face.verts, key=lambda v: v.index)]
            for corner in range(3):
                by_edge[(keys[corner], keys[(corner + 1) % 3])].append(face.index)

        sheets = []
        unvisited = set(flagged)
        while unvisited:
            seed = unvisited.pop()
            group = [seed]
            queue = deque([seed])
            while queue:
                current = bm.faces[queue.popleft()]
                keys = [v.index
                        for v in sorted(current.verts, key=lambda v: v.index)]
                for corner in range(3):
                    pair = (keys[corner], keys[(corner + 1) % 3])
                    for neighbour in by_edge.get(pair, ()):
                        if neighbour in unvisited:
                            unvisited.remove(neighbour)
                            group.append(neighbour)
                            queue.append(neighbour)
            corners = [v.co for i in group for v in bm.faces[i].verts]
            if not corners:
                continue
            box_low = [round(min(c[i] for c in corners), 3) for i in range(3)]
            box_high = [round(max(c[i] for c in corners), 3) for i in range(3)]
            gap = [gaps[i] for i in group if i in gaps]
            sheets.append({
                "faces": len(group),
                "area": round(sum(bm.faces[i].calc_area() for i in group), 6),
                "gap": round(sum(gap) / len(gap), 5) if gap else None,
                "min": box_low,
                "max": box_high,
            })
        sheets.sort(key=lambda row: -row["area"])
        flagged_area = sum(row["area"] for row in sheets)
        print("LAPS " + json.dumps({
            "mesh": obj.name,
            "faces": len(bm.faces),
            "flagged": len(flagged),
            "sheets": len(sheets),
            "flaggedArea": round(flagged_area, 6),
            "share": round(flagged_area / max(sum(f.calc_area() for f in bm.faces), 1e-9), 5),
            "rows": sheets[:40],
        }))
        bm.free()


main()
