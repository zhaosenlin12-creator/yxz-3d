"""Find the sheet folded back onto the visor.

The scan left a flat sheet of the helmet's own trim lying on the visor,
under the eye and to the side of the smile, running out past the edge of
the face.  A sheet that lies on a surface has its back to that surface,
so it is found by its normals: a face on the front of the character
points forwards, and the folded sheet points backwards.

Usage:
  blender -b -P scripts/probe_yxz_fold.py -- --glb <file>
    [--x0 0.17] [--x1 0.27] [--y0 -0.22] [--y1 -0.02] [--z0 -0.02] [--z1 0.18]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = Path(value_after("--glb"))
    box = [float(value_after(name, default)) for name, default in (
        ("--x0", 0.17), ("--x1", 0.27),
        ("--y0", -0.22), ("--y1", -0.02),
        ("--z0", -0.02), ("--z1", 0.18),
    )]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active

    inward = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if not (box[0] <= centre.x <= box[1]
                and box[2] <= centre.y <= box[3]
                and box[4] <= centre.z <= box[5]):
            continue
        # The character's face is at +X, so a face that points away from
        # +X is pointing back into the head.
        if face.normal.x > -0.25:
            continue
        inward.append(face)

    print("YXZ_FOLD inward=%d" % len(inward))
    if inward:
        uvs = np.array([[loop[uv_layer].uv.x, loop[uv_layer].uv.y]
                        for face in inward for loop in face.loops])
        print("YXZ_FOLD_UV " + json.dumps({
            "low": [round(float(v), 4) for v in uvs.min(axis=0)],
            "high": [round(float(v), 4) for v in uvs.max(axis=0)],
        }))

    # The same faces, painted, so the sheet can be seen in the render.
    for face in bm.faces:
        if face in inward:
            face.material_index = 1
    material = bpy.data.materials.new("fold")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.9, 0.05, 0.05, 1.0)
    body.data.materials.append(material)
    bm.to_mesh(body.data)
    bm.free()


if __name__ == "__main__":
    main()
