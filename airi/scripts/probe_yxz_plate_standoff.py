"""How far the mouth plate floats above the face, ring by ring.

The plate is a sheet of the face's own surface with a hole in it.  It
lies on the surface the face had *before* the muzzle was hollowed, so
it floats above the hollowed face by as much as the hollow is deep.
That float is what puts a second, brighter edge along the mouth: the
plate's rim catches the rim light where the face around it does not.

This prints the float per ring, so it can be said whether the plate
needs to be seated on the face or whether the edge is something else.

    python scripts/probe_yxz_plate_standoff.py <model.vrm>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face  # noqa: E402


def sample_height(points, positions, triangles):
    """The height of a surface at each point, straight down."""
    corners = positions[triangles]
    a = corners[:, 0]
    b = corners[:, 1]
    c = corners[:, 2]
    ab = corners[:, 1] - a
    ac = corners[:, 2] - a
    d00 = ab[:, 0] * ab[:, 0] + ab[:, 1] * ab[:, 1]
    d01 = ab[:, 0] * ac[:, 0] + ab[:, 1] * ac[:, 1]
    d11 = ac[:, 0] * ac[:, 0] + ac[:, 1] * ac[:, 1]
    denom = d00 * d11 - d01 * d01
    usable = np.abs(denom) > 1e-22
    px = points[:, 0][:, None]
    py = points[:, 1][:, None]
    d20 = (px - a[None, :, 0]) * ab[None, :, 0] \
        + (py - a[None, :, 1]) * ab[None, :, 1]
    d21 = (px - a[None, :, 0]) * ac[None, :, 0] \
        + (py - a[None, :, 1]) * ac[None, :, 1]
    with np.errstate(all="ignore"):
        wb = (d11[None, :] * d20 - d01[None, :] * d21) / denom[None, :]
        wc = (d00[None, :] * d21 - d01[None, :] * d20) / denom[None, :]
    wa = 1.0 - wb - wc
    inside = (wa >= -1e-9) & (wb >= -1e-9) & (wc >= -1e-9) & usable[None, :]
    z = wa * a[None, :, 2] + wb * b[None, :, 2] + wc * c[None, :, 2]
    z = np.where(inside, z, -np.inf)
    best = z.argmax(axis=1)
    rows = np.arange(len(points))
    found = z[rows, best]
    return np.where(np.isfinite(found), found, np.nan), inside.any(axis=1)


def main() -> None:
    path = Path(sys.argv[1])
    asset = Asset(path)
    document = asset.document
    meshes = document["meshes"]
    body_index = next(
        i for i, mesh in enumerate(meshes)
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(
        i for i, mesh in enumerate(meshes)
        if mesh.get("name") == "YXZ_Mouth")

    face = Face(asset, body_index)
    primitive = meshes[mouth_index]["primitives"][0]
    plate = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    count = len(plate)
    rings, segments = 28, 144
    if rings * segments != count:
        for candidate in range(4, 200):
            if count % candidate:
                continue
            if count // candidate <= 64:
                rings, segments = count // candidate, candidate
                break
    print("YXZ_STANDOFF plate %d points, grid %dx%d" % (count, rings, segments))

    grid = plate.reshape(rings, segments, 3)
    centre = grid[0].mean(axis=0)
    # The face's triangles near the mouth, so the height under each plate
    # point can be read off the face rather than guessed at.
    near = face.near(centre, 0.09)
    triangles = face.triangles[near]

    print("ring   x-extent   y-extent    float mm (min/mean/max)")
    for ring in range(rings):
        points = grid[ring]
        height, _ = sample_height(points, face.positions, triangles)
        float_m = (points[:, 2] - height) * 1000.0
        float_m = float_m[np.isfinite(float_m)]
        if not len(float_m):
            continue
        print("%4d  %8.2f %9.2f   %7.3f %7.3f %7.3f" % (
            ring,
            (points[:, 0].max() - points[:, 0].min()) * 500.0,
            (points[:, 1].max() - points[:, 1].min()) * 500.0,
            float_m.min(), float_m.mean(), float_m.max(),
        ))


if __name__ == "__main__":
    main()
