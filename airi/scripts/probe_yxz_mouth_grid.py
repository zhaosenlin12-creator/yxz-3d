"""
The mouth plate's grid, measured.

The plate is a ring of the hole's rim, then rings out to a fixed edge,
and the hole is what the mouth is.  The dish behind it is what shows
through.  What looks wrong on screen is between the two: the dish is
folded and torn, and it is torn because it is built by following the
plate's own surface, and the plate's surface folds where the lower lip
turns over.

So this prints the rim of the hole for each viseme -- where it is, how
high it sits, and where the plate's surface has a cliff under it -- which
is the shape the dish has to cover without folding.

    python scripts/probe_yxz_mouth_grid.py [path/to/yxz.vrm]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


RINGS = 28
SEGMENTS = 144


def plate(asset, document):
    index = next(i for i, mesh in enumerate(document["meshes"])
                 if mesh.get("name") == "YXZ_Mouth")
    mesh = document["meshes"][index]
    primitive = mesh["primitives"][0]
    position = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    targets = {}
    for target in mesh.get("extras", {}).get("targetNames", []):
        pass
    for name, target in zip(mesh.get("extras", {}).get("targetNames", []),
                            mesh.get("targets", [])):
        accessor = document["accessors"][target["POSITION"]]
        delta = asset.accessor(accessor).astype(np.float64)
        targets[name] = position + delta
    return position, targets


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
    asset = Asset(path)
    document = asset.document

    position, targets = plate(asset, document)
    print("PLATE %d verts, %d rings of %d" % (len(position), RINGS, SEGMENTS))

    def rim(points):
        return points[:SEGMENTS].reshape(-1, 3)

    states = {"Basis": position}
    states.update(targets)

    for name, points in states.items():
        edge = rim(points)
        centre = edge.mean(axis=0)
        span = edge.max(axis=0) - edge.min(axis=0)
        print("")
        print("  %-10s centre %s  span %s" % (
            name,
            np.round(centre, 4).tolist(),
            np.round(span, 4).tolist()))

    # The cliff: where the plate's own surface turns over.  A ring is
    # placed on the face, and where the face drops away, the step between
    # one ring and the next is large.  That is where the dish tears.
    print("")
    print("CLIFFS in the plate's own surface (step between neighbouring rings)")
    grid = position.reshape(RINGS, SEGMENTS, 3)
    steps = np.linalg.norm(np.diff(grid, axis=0), axis=-1)
    for ring in range(RINGS - 1):
        worst = steps[ring].max()
        if worst > 0.0008:
            at = int(np.argmax(steps[ring]))
            print("  ring %2d -> %2d  step %.4f at segment %3d  (%.4f, %.4f, %.4f)" % (
                ring, ring + 1, worst, at,
                grid[ring, at, 0], grid[ring, at, 1], grid[ring, at, 2]))

    # The hole's rim, sampled round, for the two shapes that matter: the
    # closed slit and the widest open mouth.
    for name in ("Basis", "aa", "ou"):
        if name not in states:
            continue
        edge = rim(states[name])
        print("")
        print("RIM %s" % name)
        for segment in range(0, SEGMENTS, 8):
            point = edge[segment]
            print("  seg %3d  x % .4f  y % .4f  z % .4f" % (
                segment, point[0], point[1], point[2]))


if __name__ == "__main__":
    main()
