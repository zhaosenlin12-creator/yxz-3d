"""Measure where the YXZ arms actually are in the source mesh.

The Tripo asset ships with one arm raised in a wave and the other hanging
down holding a book.  A skeleton that assumes two hanging arms cannot bind
to that: the raised hand ends up closer to the head bone than to the hand
bone, so distance weighting hands it to the head and the arm tears itself
apart as soon as it rotates.

This prints the arm's actual shape as a grid over the (y, z) plane, which is
where the answer can be read off: the measured frame has the character
facing +X with +Z up, so y is the character's right/left axis and z is up.

  blender -b -P scripts/probe_yxz_arm_landmarks.py -- --source <glb>
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = value_after("--source")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    count = len(mesh.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    x, y, z = coords[:, 0], coords[:, 1], coords[:, 2]

    print("YXZ_BBOX min " + str([round(float(v), 4) for v in coords.min(axis=0)]))
    print("YXZ_BBOX max " + str([round(float(v), 4) for v in coords.max(axis=0)]))
    print("YXZ_VERTS " + str(count))

    # Extremes, so the raised hand and the hanging hand can be located.
    for label, index, sign in (("maxY", 1, 1), ("minY", 1, -1),
                               ("maxZ", 2, 1), ("minZ", 2, -1),
                               ("maxX", 0, 1), ("minX", 0, -1)):
        pick = int(np.argmax(sign * coords[:, index]))
        print(f"YXZ_EXTREME {label} "
              + str([round(float(v), 4) for v in coords[pick]]))

    # A coarse occupancy map: for every (y, z) cell, the smallest and
    # largest x of the vertices inside it.  The torso reads as a solid
    # column, the hanging arm as a band at negative y and the raised arm as
    # a band climbing towards the head at positive y.
    y_lo = float(value_after("--ymin", coords[:, 1].min()))
    y_hi = float(value_after("--ymax", coords[:, 1].max()))
    z_lo = float(value_after("--zmin", coords[:, 2].min()))
    z_hi = float(value_after("--zmax", coords[:, 2].max()))
    resolution = int(value_after("--res", 24))
    y_edges = np.linspace(y_lo, y_hi, resolution + 1)
    z_edges = np.linspace(z_lo, z_hi, resolution + 1)
    print("YXZ_PROFILE rows=z(top->bottom) cols=y(left->right) cell=minX/maxX")
    for zi in range(len(z_edges) - 2, -1, -1):
        row = []
        for yi in range(len(y_edges) - 1):
            mask = ((y >= y_edges[yi]) & (y < y_edges[yi + 1])
                    & (z >= z_edges[zi]) & (z < z_edges[zi + 1]))
            if not mask.any():
                row.append("  --  ")
                continue
            lo = float(x[mask].min())
            hi = float(x[mask].max())
            row.append(f"{lo:+.2f}/{hi:+.2f}")
        print(f"YXZ_ROW z={z_edges[zi]:+.3f}..{z_edges[zi + 1]:+.3f} | "
              + " ".join(row))
    print("YXZ_Y_EDGES " + " ".join(f"{v:+.3f}" for v in y_edges))

    # The raised hand: the only geometry that reaches up and out past the
    # helmet, so it can be picked out by scoring "up and to the character's
    # left" and taking the extremes.
    score = -y + 0.7 * z
    candidates = np.where(z > 0.12)[0]
    order = candidates[np.argsort(-score[candidates])]
    print("YXZ_FINGERTIPS")
    for index in order[:24]:
        print("  " + str([round(float(v), 4) for v in coords[index]]))

    for label, mask in (
        ("raisedArm", (y < -0.20) & (z > 0.15)),
        ("raisedHand", (y < -0.24) & (z > 0.22)),
        ("hangingArm", (y > 0.20) & (z < 0.10) & (z > -0.25)),
    ):
        if not mask.any():
            print(f"YXZ_REGION {label} empty")
            continue
        block = coords[mask]
        print(f"YXZ_REGION {label} count={int(mask.sum())} "
              + "min " + str([round(float(v), 4) for v in block.min(axis=0)]) +
              " max " + str([round(float(v), 4) for v in block.max(axis=0)]) +
              " mean " + str([round(float(v), 4) for v in block.mean(axis=0)]))


if __name__ == "__main__":
    main()
