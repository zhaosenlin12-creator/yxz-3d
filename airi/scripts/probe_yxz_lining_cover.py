"""Does the lining behind the mouth actually cover the opening?

The pale line along the lips is the question this answers.  It is a
hole in the geometry if, looking straight down at some point of the
mouth's rim, there is nothing behind it but the hollowed face; it is
shading if there is always something dark behind it.

For every point of the mouth's rim this finds the lining's own surface
at the same point in the face's plane and compares the two depths, so
the answer is a number rather than an opinion: how far behind the
lining is, and how much of the rim has nothing behind it at all.

    python scripts/probe_yxz_lining_cover.py <model.vrm>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


def sample(points, positions, triangles):
    """The height of a surface at each point, straight down."""
    corners = positions[triangles]
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    ab, ac = b - a, c - a
    d00 = ab[:, 0] * ab[:, 0] + ab[:, 1] * ab[:, 1]
    d01 = ab[:, 0] * ac[:, 0] + ab[:, 1] * ac[:, 1]
    d11 = ac[:, 0] * ac[:, 0] + ac[:, 1] * ac[:, 1]
    denom = d00 * d11 - d01 * d01
    usable = np.abs(denom) > 1e-22
    px, py = points[:, 0][:, None], points[:, 1][:, None]
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
    return np.where(np.isfinite(found), found, np.nan)


def main() -> None:
    path = Path(sys.argv[1])
    asset = Asset(path)
    document = asset.document
    meshes = document["meshes"]

    def mesh(name):
        index = next(i for i, m in enumerate(meshes) if m.get("name") == name)
        primitive = meshes[index]["primitives"][0]
        positions = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
        indices = asset.accessor(primitive["indices"]).reshape(-1, 3).astype(np.int64)
        return positions, indices

    plate, plate_tri = mesh("YXZ_Mouth")
    cavity, cavity_tri = mesh("YXZ_MouthCavity")

    rings, segments = 28, 144
    if rings * segments != len(plate):
        for candidate in range(4, 200):
            if len(plate) % candidate:
                continue
            if len(plate) // candidate <= 64:
                rings, segments = len(plate) // candidate, candidate
                break
    grid = plate.reshape(rings, segments, 3)
    rim = grid[0]
    print("YXZ_COVER plate %d points (%dx%d), lining %d points"
          % (len(plate), rings, segments, len(cavity)))

    # Where the lining sits, straight below every point of the rim.
    lining_z = sample(rim, cavity, cavity_tri)
    gap = rim[:, 2] - lining_z
    covered = np.isfinite(gap)
    print("rim points covered by the lining: %d / %d" % (int(covered.sum()), len(rim)))
    if covered.any():
        print("lining depth behind the rim (mm): min %.3f  mean %.3f  max %.3f"
              % (gap[covered].min() * 1000, gap[covered].mean() * 1000,
                 gap[covered].max() * 1000))
        print("rim points where the lining is in front of the lip: %d"
              % int((gap[covered] <= 0).sum()))

    # The lining's own footprint: does it reach past the mouth's ends?
    print("lining footprint  x %.1f..%.1f mm   y %.1f..%.1f mm"
          % (cavity[:, 0].min() * 1000, cavity[:, 0].max() * 1000,
             cavity[:, 1].min() * 1000, cavity[:, 1].max() * 1000))
    print("mouth rim footprint x %.1f..%.1f mm   y %.1f..%.1f mm"
          % (rim[:, 0].min() * 1000, rim[:, 0].max() * 1000,
             rim[:, 1].min() * 1000, rim[:, 1].max() * 1000))

    # The pale line runs along the middle of the mouth, so the middle is
    # what matters: the lining's height across the slit, against the
    # plate's own height on either side of it.
    middle = rim[np.abs(rim[:, 1]) < rim[:, 1].max() * 0.4]
    if len(middle):
        lining_middle = sample(middle, cavity, cavity_tri)
        print("across the slit: lining %s .. %s mm in front of the plate"
              % (round(float(np.nanmin(lining_middle - middle[:, 2])) * 1000, 3),
                 round(float(np.nanmax(lining_middle - middle[:, 2])) * 1000, 3)))


if __name__ == "__main__":
    main()
