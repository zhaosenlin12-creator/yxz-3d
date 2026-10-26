"""Take the rebuilt crown off and see what is underneath it.

The crown that was built to close the tear in the helmet is a cap of a
sphere, and it is drawn over the shell that was already there.  Where
the shell is intact the two surfaces are a fraction of a millimetre
apart and the depth test cannot choose between them, and the head comes
out of the render as a drift of torn white flakes.

This removes the cap and photographs what is left, which is the shell
the cap was hiding.

Usage:
  blender -b -P scripts/probe_yxz_drop_cap.py -- \
    --glb <glb> --out <dir> [--uv 0.49792,0.12259]
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
import bmesh


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out"))
    uv_parts = value_after("--uv", "0.49792,0.12259").split(",")
    uv_x, uv_y = float(uv_parts[0]), float(uv_parts[1])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    doomed = []
    for face in bm.faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            if abs(uv.x - uv_x) < 1e-4 and abs(uv.y - uv_y) < 1e-4:
                doomed.append(face)
                break
    print("YXZ_CAP_FACES %d" % len(doomed))
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces],
                     context="VERTS")
    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "nocap.blend"))
    bpy.ops.export_scene.gltf(filepath=str(out / "nocap.glb"), export_format="GLB")
    print("YXZ_NOCAP " + str(out / "nocap.glb"))


if __name__ == "__main__":
    main()
