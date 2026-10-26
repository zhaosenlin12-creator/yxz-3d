"""Measure the arm chain, visor surface and helmet so the rig is not guessed.

The banded silhouette probe cannot separate an arm from a torso, so this one
isolates each limb with a side filter and reports the visor depth directly in
front of the eye and mouth positions that the decal scripts already located.

  blender -b -P scripts/probe_yxz_face_limbs.py -- --glb <path>
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def rng(values, index: int) -> list:
    return [round(min(v[index] for v in values), 4), round(max(v[index] for v in values), 4)]


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )
    co = [(v.co.x, v.co.y, v.co.z) for v in body.data.vertices]

    # Arm trace: keep only verts well outside the torso envelope so the bands
    # describe the limb rather than the chest it overlaps in depth.
    arms = {}
    for side, sign in (("R", 1.0), ("L", -1.0)):
        bands = []
        for i in range(22):
            z0 = -0.42 + i * 0.028
            z1 = z0 + 0.028
            slab = [c for c in co if z0 <= c[2] < z1 and sign * c[1] > 0.14]
            row = {"z": round((z0 + z1) / 2, 4), "verts": len(slab)}
            if len(slab) >= 40:
                # depthX says where the elbow sits, widthY how thick the limb is.
                row["x"] = rng(slab, 0)
                row["y"] = rng(slab, 1)
            bands.append(row)
        arms[side] = bands

    def surface(y: float, z: float, radius: float) -> dict:
        near = [c for c in co if (c[1] - y) ** 2 + (c[2] - z) ** 2 <= radius * radius]
        return {"frontX": rng(near, 0)[1], "backX": rng(near, 0)[0],
                "yRange": rng(near, 1), "zRange": rng(near, 2), "verts": len(near)}

    # Helmet: drop the ear modules by ignoring |y| > 0.25.
    helmet = []
    for i in range(20):
        z0 = -0.06 + i * 0.025
        z1 = z0 + 0.025
        slab = [c for c in co if z0 <= c[2] < z1 and abs(c[1]) <= 0.20]
        if len(slab) >= 40:
            helmet.append({"z": round((z0 + z1) / 2, 4), "x": rng(slab, 0), "y": rng(slab, 1)})

    report = {
        "glb": glb,
        "arms": arms,
        "helmet": helmet,
        "eyeL": surface(-0.095, 0.18, 0.030),
        "eyeR": surface(0.095, 0.18, 0.030),
        "mouth": surface(0.0, 0.058, 0.035),
        "visorTop": surface(0.0, 0.26, 0.040),
    }
    print("YXZ_FACE " + json.dumps(report))


if __name__ == "__main__":
    main()
