"""Take the glass bubble off the head, and touch nothing else.

The design has a clear bubble over the helmet with the halo ring round
it, and in the scan that bubble is a separate skin of geometry standing
clear of the white shell.  Rendered, it is the reason the character
reads as glassy and hazy: a smooth, hazy dome sits over the top of the
head, it catches the key light across its whole width, and it hides the
badge on the forehead underneath it.

The previous answer to that was to take the bubble off *and* rebuild the
crown of the helmet over the top of the hole the bubble's rim had torn
in it.  The rebuild worked, but it put a smooth cap where a face had
been, and a cap with no face of the scan on it is a smooth dome: it
reads as a bubble again, and the badge is gone with the crown it sat on.

So this does the half of the job that is worth doing.  The bubble goes.
The crown of the helmet underneath it is the scan's own face, with the
badge on it, and it is left exactly as the scan made it.

The bubble is the skin of geometry that stands clear of the sphere the
helmet is built on, so it is found by how far out from the middle of the
head it sits.  It is taken off face by face rather than shell by shell,
because the scan welded the bubble to the helmet in places and there is
no shell that is only bubble.

The badge is a raised emblem and stands clear of the helmet by about as
much as the bubble did, so it is kept by where it is rather than by how
big it is.

Usage:
  blender -b -P scripts/remove_yxz_bubble.py -- \
    --source <glb> --output <glb> [--bubble-radius 0.300] \
    [--centre 0.038,-0.001,0.094] [--keep-box ...] [--report-only]
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
    bubble_radius = float(value_after("--bubble-radius", "0.300"))
    far_radius = float(value_after("--far-radius", "0.42"))
    floor = float(value_after("--floor", "-0.16"))
    keep = value_after("--keep-box", "0.15,-0.22,0.22,0.28,0.14,0.42")
    keep_box = [float(v) for v in keep.split(",")]
    report_only = "--report-only" in sys.argv

    def in_keep_box(point):
        return all(keep_box[axis] <= point[axis] <= keep_box[axis + 3]
                   for axis in range(3))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    doomed = []
    low = [1e9, 1e9, 1e9]
    high = [-1e9, -1e9, -1e9]
    for face in bm.faces:
        middle = face.calc_center_median()
        distance = (middle - centre).length
        if distance <= bubble_radius:
            continue
        # The bubble is on the head.  The rest of the character is a long
        # way from the head's centre and is not glass.
        if distance > far_radius:
            continue
        # The bubble is a skin over the head; it does not go below the
        # head, and the shoulders and the wings are below it.
        if middle.z < centre.z + floor:
            continue
        # The badge is a raised emblem on the forehead and it stands
        # clear of the helmet by about as much as the bubble did.
        if in_keep_box(middle):
            continue
        doomed.append(face)
        for axis in range(3):
            low[axis] = min(low[axis], middle[axis])
            high[axis] = max(high[axis], middle[axis])

    print("YXZ_BUBBLE_REPORT " + json.dumps({
        "faces": len(doomed),
        "box": [round(v, 4) for v in low + high],
    }))
    if report_only:
        return

    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format='GLB',
        export_apply=False,
        export_yup=True,
        export_texcoords=True,
        export_normals=True,
        export_materials='EXPORT',
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=True,
    )
    print("YXZ_BUBBLE_REMOVED " + str(output))


if __name__ == "__main__":
    main()
