"""Cut the shattered bubble off the crown of the helmet.

The design puts a clear bubble over the helmet.  In the scan that bubble
is a skin of geometry standing clear of the white shell, and it has
shattered: what survives is a drift of shards fanning off the back of
the crown, welded to the shell along the lines where the two were one
piece before the break.  Those shards are what the character reads as
broken -- a bare hinge torn open, with plates standing off it like
leaves off a torn page.

They cannot be taken off as separate objects, because they are not
separate any more: they are joined to the helmet along their roots, so
there is no island to delete and no boundary to find.  What does still
tell them apart is the number the whole design is built on.  The helmet
is very nearly a sphere centred on the middle of the head, and its own
surface sits at a radius of about 0.2965.  Everything out past that is
the bubble -- roots, shards and all -- because nothing belonging to the
helmet stands further out than the helmet.

So the cut is a sphere.  A face goes when every one of its corners is
outside it, which leaves the helmet with a clean rim following the
triangle edges and the shards taken off flush at the root.  Testing the
corners rather than the middle matters: a face with one corner outside
and two inside would be cut in half and leave a ragged lip.

Usage:
  blender -b -P scripts/trim_yxz_crown.py -- \
    --source <glb> --output <glb> [--centre 0.038,-0.001,0.094] \
    [--radius 0.2975] [--min-z 0.12]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    radius = float(value_after("--radius", "0.2975"))
    min_z = float(value_after("--min-z", "0.12"))
    report_only = "--report-only" in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    doomed = []
    for face in bm.faces:
        middle = face.calc_center_median()
        if middle.z < min_z:
            continue
        if min((vertex.co - centre).length for vertex in face.verts) <= radius:
            continue
        doomed.append(face)

    report = {
        "radius": radius,
        "facesBefore": len(bm.faces),
        "cutFaces": len(doomed),
    }

    if doomed and not report_only:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
        bm.normal_update()
        bm.to_mesh(body.data)
        body.data.update()
        report["facesAfter"] = len(body.data.polygons)

    bm.free()
    print("YXZ_TRIM " + json.dumps(report))

    if not report_only:
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


if __name__ == "__main__":
    main()
