"""Split the reconstructed body into the parts the rig treats differently.

Hunyuan3D-2 hands back one mesh with the halo fused to the crown as a flat
disc.  A flat disc is not a halo -- the reference art shows a ring of light
floating behind the helmet -- so the disc is cut out here and the ring is
rebuilt procedurally instead.

  python split_body.py --source .run/shape/body.glb --out .run/shape
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scene = trimesh.load(args.source)
    mesh = scene.to_geometry()
    parts = mesh.split(only_watertight=False)
    parts.sort(key=lambda part: -len(part.vertices))

    body = parts[0]
    extras = parts[1:]

    # The halo is the flat disc: it sits above the crown, is wide and thin,
    # and it is the only piece whose top is the highest point of the model.
    halo = None
    keep = []
    for part in extras:
        lo, hi = part.bounds
        thin = (hi[1] - lo[1]) < 0.2
        wide = max(hi[0] - lo[0], hi[2] - lo[2]) > 0.5
        high = hi[1] > body.bounds[1][1] - 0.05
        if halo is None and thin and wide and high:
            halo = part
        else:
            keep.append(part)

    if halo is None:
        raise SystemExit("no halo disc found in the mesh")

    core = body
    for part in keep:
        core = trimesh.util.concatenate([core, part])

    core.export(out / "body_core.glb")
    print(f"YXZ_SPLIT core v={len(core.vertices)} f={len(core.faces)} "
          f"bounds={np.round(core.bounds, 3).tolist()}")
    print(f"YXZ_SPLIT halo v={len(halo.vertices)} "
          f"bounds={np.round(halo.bounds, 3).tolist()}")


if __name__ == "__main__":
    main()
