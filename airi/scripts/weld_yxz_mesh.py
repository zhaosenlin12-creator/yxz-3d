"""Weld the scan's tiles into one shell.

The character arrives from Tripo as a merge of several hundred separate
sheets.  A handful of them are the character; the rest are its tiles, and
the tiles were cut apart rather than joined, so along every seam between
two of them the surface stops.  Each side of the seam owns its own
vertices and the two sets sit a fraction of an edge length apart, so the
seam is a hairline gap rather than a matching pair of edges.

Nothing closes a gap like that.  The hole repair only works on openings
it can judge, a seam that runs the length of the arm is not an opening it
will touch, and a gap that narrow survives every later pass.  What the gap
does is show the dark inside of the model through the white shell, which
is a black line drawn along every tile boundary -- and a white shell with
a hundred black lines across it is the shattered look the whole pipeline
exists to remove.

So the seams are welded shut before anything else looks at them.  The
distance is the whole decision: too small and the seam survives, too large
and the model melts, because the tiles are not far apart in space -- they
are the same surface seen twice.

Usage:
  blender -b -P scripts/weld_yxz_mesh.py -- \
    --source <glb> --output <glb> [--dist 0.0025] [--report-only]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def open_edges(bm):
    bm.edges.index_update()
    return sum(1 for edge in bm.edges if len(edge.link_faces) == 1)


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    dist = float(value_after("--dist", "0.0025"))
    report_only = "--report-only" in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    before_verts = len(bm.verts)
    before_faces = len(bm.faces)
    before_open = open_edges(bm)

    # `remove_doubles` merges the two sets of vertices that sit on either
    # side of a seam.  It leaves the faces that now cover the same ground
    # twice, and a doubled face is a face that fights with its own twin for
    # the same pixel -- the other half of the shattered look, and the reason
    # the flakes have to be swept as well as welded.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=dist)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    report = {
        "source": str(source),
        "dist": dist,
        "vertsBefore": before_verts,
        "vertsAfter": len(bm.verts),
        "facesBefore": before_faces,
        "facesAfter": len(bm.faces),
        "openBefore": before_open,
        "openAfter": open_edges(bm),
    }
    print("YXZ_WELDED " + json.dumps(report))

    if report_only:
        bm.free()
        return

    # Faces with no area are noise left by the weld: they have no place on
    # the surface and they shade as black smears when they survive.
    dead = [face for face in bm.faces if face.calc_area() <= 1e-12]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.normal_update()
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

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
    print("YXZ_WELD_WRITTEN " + str(output))


if __name__ == "__main__":
    main()
