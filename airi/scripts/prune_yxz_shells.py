"""Take the dust and the torn scraps off the scan.

The character is a scan, and a scan is stitched from pieces.  Two things
come out of that stitching that have to be taken away before the model
can be called finished.

The first is dust.  The tear leaves whole triangles of surface with
nothing attached to them, and the model arrives with over eight thousand
of them: one triangle each, a couple of millimetres across, scattered
over the whole figure.  They are the dirt on the shoulder, the freckles
on the arm, the grain on the visor.  They are not part of the toy, and
they are what makes the surface look dusty rather than painted.  A
scrap is told from a part by its size: dust covers a couple of square
millimetres of surface and nothing else does.

The second is the torn scrap.  Where the stitch went wrong, a piece of
the surface came away as a feather -- a spine with barbs off it, hanging
off the crown of the head, where the wreck of an old halo used to lie
across it.  These are much bigger than the dust, so size alone will not
do; they are found by where they are.  The crown of the head is a dome
built from a handful of large pieces, and every small piece lying on it
is a scrap of the tearing, because a dome of that shape has no small
parts to it.  The rule is therefore geometric: a shell that lies wholly
inside the crown and is too small to be a piece of the dome is a scrap.

Usage:
  blender -b -P scripts/prune_yxz_shells.py -- \
    --source <glb> --output <glb> [--min-area 0.00015] \
    [--crown-box0 x0,y0,z0,x1,y1,z1] [--crown-faces 500] [--apply]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def boxes_after(name):
    """Every box given on the command line, as a list of corners."""
    boxes = []
    index = 0
    while True:
        key = "%s%d" % (name, index)
        if key not in sys.argv:
            break
        index += 1
        text = sys.argv[sys.argv.index(key) + 1]
        boxes.append([float(p) for p in text.split(",")])
    return boxes


def shells(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
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


def within(low, high, box):
    """Is a shell wholly inside the box?"""
    return (low[0] >= box[0] and low[1] >= box[1] and low[2] >= box[2]
            and high[0] <= box[3] and high[1] <= box[4] and high[2] <= box[5])


def main():
    source = value_after("--source")
    output = value_after("--output")
    min_area = float(value_after("--min-area", "0.00015"))
    crown_faces = int(value_after("--crown-faces", "500"))
    crown_boxes = boxes_after("--crown-box")
    apply = "--apply" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = shells(bm)

    dust = []
    scraps = []
    for number, group in enumerate(groups):
        area = float(sum(face.calc_area() for face in group))
        points = np.array([[v.co.x, v.co.y, v.co.z] for f in group
                           for v in f.verts])
        low = points.min(axis=0)
        high = points.max(axis=0)
        record = {"shell": number, "faces": len(group),
                  "area": round(area, 7),
                  "low": [round(float(v), 4) for v in low],
                  "high": [round(float(v), 4) for v in high]}
        if area < min_area:
            record["why"] = "dust"
            dust.append(record)
            continue
        if (len(group) < crown_faces
                and any(within(low, high, box) for box in crown_boxes)):
            record["why"] = "scrap"
            scraps.append(record)
            continue

    report = {
        "shells": len(groups),
        "dustShells": len(dust),
        "dustFaces": sum(r["faces"] for r in dust),
        "scrapShells": len(scraps),
        "scrapFaces": sum(r["faces"] for r in scraps),
        "scrapShellsDetail": scraps[:40],
    }
    print("YXZ_PRUNE " + json.dumps(report))

    if apply:
        doomed = []
        for record in dust + scraps:
            doomed.extend(groups[record["shell"]])
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces],
                         context="VERTS")
        bm.to_mesh(body.data)
        bm.free()
        body.data.update()
        print("YXZ_PRUNED " + json.dumps({
            "removedFaces": len(doomed),
            "removedShells": len(dust) + len(scraps),
        }))
        bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


main()
