"""Smooth the light on the shell without moving the shell.

The scan's face is crumpled: over the cheeks and the chin the surface is
covered in creases and facets a fraction of a millimetre deep.  Moving the
vertices to flatten that is not an option.  Where the scan folded sheets
against sheets, a smoothing pass pulls a vertex on one sheet straight
through the sheet it is resting on and tears a hole in the face, and the
cap that is supposed to stop that only shrinks how much noise comes off
before the tears start.

None of that has to happen, because the crumple is only visible through
the light.  What catches a highlight and turns it into a scratch across
the cheek is not the shape, it is the normal: a crease a tenth of a
millimetre deep swings the normal far enough to swing the whole
highlight with it.  So the normals are averaged instead of the positions.

Averaging a vertex's face normals gives the direction the surface is
generally heading, which is smooth by construction, and a couple of
passes of averaging *those* along the mesh takes out the variation that a
single average leaves behind.  The silhouette, the panel lines and every
crease the design actually put there are untouched, because not one
vertex has moved -- and nothing can tear, because nothing has moved.

The result is written back as custom split normals rather than as face
normals, so the exporter carries it into the VRM and the page shades the
character with it.

Usage:
  blender -b -P scripts/smooth_yxz_normals.py -- \
    --source <glb> --output <glb> [--passes 3]
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


def face_normals(bm):
    """Each vertex's direction, weighted by how much surface faces it."""
    bm.verts.index_update()
    totals = {}
    for vertex in bm.verts:
        totals[vertex.index] = Vector((0.0, 0.0, 0.0))
    for face in bm.faces:
        weight = face.calc_area()
        # A face with no area has no direction either, and adding it would
        # put a zero vector into the sum.  The repair can leave a few of
        # them behind where a patch was grown onto a rim.
        if weight <= 0.0 or face.normal.length <= 0.0:
            continue
        for vertex in face.verts:
            totals[vertex.index] += face.normal * weight
    return {index: (value.normalized() if value.length > 0
                    else Vector((0.0, 0.0, 1.0)))
            for index, value in totals.items()}


def relax(bm, directions, passes):
    """Average each direction with its neighbours', and renormalise."""
    current = directions
    for _ in range(passes):
        following = {}
        for vertex in bm.verts:
            total = Vector((0.0, 0.0, 0.0))
            for edge in vertex.link_edges:
                total += current[edge.other_vert(vertex).index]
            following[vertex.index] = total
        current = {index: (value.normalized()
                           if value.length > 0 else directions[index])
                   for index, value in following.items()}
    return current


def main():
    source = value_after("--source")
    output = value_after("--output")
    passes = int(value_after("--passes", "3"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    report = {"passes": passes, "meshes": []}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.normal_update()
        first = face_normals(bm)
        final = relax(bm, first, passes)
        swing = [
            first[index].angle(final[index])
            if first[index].length > 0.0 and final[index].length > 0.0
            else 0.0
            for index in first
        ]
        report["meshes"].append({
            "mesh": obj.name,
            "verts": len(bm.verts),
            "meanSwingDeg": round(sum(swing) / len(swing) * 57.2958, 2),
            "maxSwingDeg": round(max(swing) * 57.2958, 2),
        })
        bm.free()
        obj.data.normals_split_custom_set_from_vertices(
            [final[vertex.index] for vertex in obj.data.vertices])
        obj.data.update()

    print("NORMALS " + json.dumps(report))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


main()
