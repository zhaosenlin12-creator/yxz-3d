"""Derive YXZ body landmarks from the mesh itself.

The hand-authored skeleton in `rig_yxz_model.py` was written from guessed
coordinates. This probe measures the actual silhouette so the rig can be built
from the mesh instead of from guesses.

  blender -b -P scripts/probe_yxz_landmarks.py -- --glb <path>
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    # The body is the dense mesh; the face controls are small overlays.
    body = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )
    co = [v.co for v in body.data.vertices]

    lo = [min(c[i] for c in co) for i in range(3)]
    hi = [max(c[i] for c in co) for i in range(3)]

    # Axis roles: the character faces +X, so X is depth, Y is width, Z is up.
    bands = 24
    profile = []
    span = hi[2] - lo[2]
    for b in range(bands):
        z0 = lo[2] + span * b / bands
        z1 = lo[2] + span * (b + 1) / bands
        slab = [c for c in co if z0 <= c[2] < z1]
        if not slab:
            continue
        profile.append(
            {
                "z": round((z0 + z1) / 2, 4),
                "count": len(slab),
                "depthX": [round(min(c[0] for c in slab), 4), round(max(c[0] for c in slab), 4)],
                "widthY": [round(min(c[1] for c in slab), 4), round(max(c[1] for c in slab), 4)],
            }
        )

    head_top = max(co, key=lambda c: c[2])

    report = {
        "glb": glb,
        "bodyMesh": body.name,
        "bounds": {"x": [lo[0], hi[0]], "y": [lo[1], hi[1]], "z": [lo[2], hi[2]]},
        "height": round(span, 4),
        "headTopVertex": [round(v, 4) for v in head_top],
        "profile": profile,
    }
    print("YXZ_LANDMARKS " + json.dumps(report))


if __name__ == "__main__":
    main()
