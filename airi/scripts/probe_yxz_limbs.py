"""Find Y/X vertex clusters per height band so limb joints come from the mesh.

Silhouette min/max per band cannot tell a leg from a wing, but occupancy
clusters can: two legs read as two separated runs, and thin plates such as the
wings read as a wide run with almost no X depth.

  blender -b -P scripts/probe_yxz_limbs.py -- --glb <path>
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def clusters(values: list[float], lo: float, hi: float, bin_size: float, min_count: int):
    """Return contiguous runs of occupied bins as [start, end, total]."""
    bins = int((hi - lo) / bin_size) + 1
    counts = [0] * bins
    for v in values:
        index = int((v - lo) / bin_size)
        if 0 <= index < bins:
            counts[index] += 1

    runs = []
    start = None
    for index, count in enumerate(counts + [0]):
        if count >= min_count and start is None:
            start = index
        elif count < min_count and start is not None:
            runs.append(
                [
                    round(lo + start * bin_size, 4),
                    round(lo + index * bin_size, 4),
                    sum(counts[start:index]),
                ]
            )
            start = None
    return runs


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    body = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )
    co = [v.co for v in body.data.vertices]
    z_lo = min(c[2] for c in co)
    z_hi = max(c[2] for c in co)

    bands = []
    steps = 26
    for b in range(steps):
        z0 = z_lo + (z_hi - z_lo) * b / steps
        z1 = z_lo + (z_hi - z_lo) * (b + 1) / steps
        slab = [c for c in co if z0 <= c[2] < z1]
        if len(slab) < 50:
            continue
        bands.append(
            {
                "z": round((z0 + z1) / 2, 4),
                "verts": len(slab),
                # min_count is scaled to the slab so thin plates stay visible.
                "yRuns": clusters(
                    [c[1] for c in slab], -0.40, 0.40, 0.01, max(6, len(slab) // 900)
                ),
                "xRuns": clusters(
                    [c[0] for c in slab], -0.28, 0.28, 0.01, max(6, len(slab) // 900)
                ),
            }
        )

    print("YXZ_LIMBS " + json.dumps({"glb": glb, "bands": bands}))


if __name__ == "__main__":
    main()
