"""Stop the face from coming through the mouth plate.

The plate is a sheet of the face's own surface, lifted a tenth of a
millimetre off it.  Where the face turns over a steep edge -- the
lower lip ends in one that stands almost upright -- the sheet cannot
follow it: the straight line between two of the sheet's own points cuts
straight through the lip, and the lip comes through the sheet.  The
result is a spray of black shards around the mouth.

The fix is not to make the sheet denser.  It is to move the lip out of
the way: the vertices that stand proud of the sheet are pushed back
until they are behind it, and the sheet -- which is opaque and carries
the paint of the face -- covers them.

    python scripts/fix_yxz_mouth_poke.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face  # noqa: E402
from rebuild_yxz_mouth import SEGMENTS, RINGS  # noqa: E402


# The mouth's centre, on the face.
CENTRE = np.array([0.0, 0.0621, 0.2501])

# How far clear of the plate a vertex has to be before it is left alone.
CLEARANCE = 0.00006

# How far back a vertex that pokes through is pushed, on top of the
# clearance.  A little more than the poke itself, so the vertex stays
# behind the sheet.
EXTRA = 0.00004

# The most a single vertex may be moved.  Beyond this the lip would
# start to look dented, and the sheet is only a tenth of a millimetre
# off the face, so a small dent is not worth a large one.
LIMIT = 0.0040


def plate_height(points, plate, indices):
    """How far forward the plate is at each point, straight down.

    Every triangle of the plate is tested against the point, and the
    ones that cover it give the height there.
    """
    a = plate[indices[:, 0]]
    b = plate[indices[:, 1]]
    c = plate[indices[:, 2]]
    ab = b - a
    ac = c - a
    d00 = ab[:, 0] * ab[:, 0] + ab[:, 1] * ab[:, 1]
    d01 = ab[:, 0] * ac[:, 0] + ab[:, 1] * ac[:, 1]
    d11 = ac[:, 0] * ac[:, 0] + ac[:, 1] * ac[:, 1]
    denom = d00 * d11 - d01 * d01
    usable = np.abs(denom) > 1e-22

    x = points[:, 0][:, None]
    y = points[:, 1][:, None]
    d20 = (x - a[None, :, 0]) * ab[None, :, 0] \
        + (y - a[None, :, 1]) * ab[None, :, 1]
    d21 = (x - a[None, :, 0]) * ac[None, :, 0] \
        + (y - a[None, :, 1]) * ac[None, :, 1]
    with np.errstate(all="ignore"):
        weight_b = (d11[None, :] * d20 - d01[None, :] * d21) / denom[None, :]
        weight_c = (d00[None, :] * d21 - d01[None, :] * d20) / denom[None, :]
    weight_a = 1.0 - weight_b - weight_c
    inside = (weight_a >= -1e-9) & (weight_b >= -1e-9) & (weight_c >= -1e-9) \
        & usable[None, :]
    z = weight_a * a[None, :, 2] \
        + weight_b * b[None, :, 2] \
        + weight_c * c[None, :, 2]
    z = np.where(inside, z, -np.inf)
    best = z.argmax(axis=1)
    rows = np.arange(len(points))
    return z[rows, best], np.isfinite(z[rows, best])


def face_normals(positions, triangles, touched):
    """The normals of the face, worked out from its own triangles."""
    corners = positions[triangles]
    normals = np.cross(corners[:, 1] - corners[:, 0],
                       corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.maximum(lengths, 1e-20)

    keep = np.zeros(len(triangles), dtype=bool)
    for vertex in touched:
        keep |= (triangles == vertex).any(axis=1)
    used = triangles[keep]
    summed = np.zeros_like(positions)
    np.add.at(summed, used[:, 0], normals[keep])
    np.add.at(summed, used[:, 1], normals[keep])
    np.add.at(summed, used[:, 2], normals[keep])
    lengths = np.linalg.norm(summed, axis=1, keepdims=True)
    good = lengths[:, 0] > 1e-12
    result = summed / np.maximum(lengths, 1e-20)
    return result, good


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])

    asset = Asset(source)
    document = asset.document
    body_index = next(
        i for i, mesh in enumerate(document["meshes"])
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(
        i for i, mesh in enumerate(document["meshes"])
        if mesh.get("name") == "YXZ_Mouth")

    face = Face(asset, body_index)
    primitive = document["meshes"][mouth_index]["primitives"][0]
    plate = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    indices = asset.accessor(primitive["indices"]).reshape(-1, 3).astype(np.int64)

    reach = 0.09
    candidates = face.near(CENTRE, reach)
    pool = np.unique(face.triangles[candidates].reshape(-1))
    points = face.positions[pool]

    height, covered = plate_height(points, plate, indices)
    if not covered.all():
        print("YXZ_POKE %d vertices are not under the plate" % int((~covered).sum()))
        points = points[covered]
        height = height[covered]
        pool = pool[covered]

    poke = points[:, 2] - height
    bad = poke > CLEARANCE
    print("YXZ_POKE face vertices under the plate %d, standing proud %d, "
          "worst %.3f mm" % (len(points), int(bad.sum()),
                             poke[bad].max() * 1000 if bad.any() else 0.0))
    if not bad.any():
        asset.save(target)
        print("YXZ_POKE nothing to do")
        return

    push = np.zeros(len(pool))
    push[bad] = np.minimum(poke[bad] + EXTRA, LIMIT)
    moved = np.zeros_like(face.positions)
    moved[pool] = face.positions[pool]
    moved[pool, 2] -= push
    # A vertex that is pushed back also goes a little further in, so
    # that it slides behind the lip rather than into it.
    moved[pool, 1] -= push * 0.25

    touched = pool[bad]
    normals, good = face_normals(moved, face.triangles, touched)
    new_normals = face.normals.copy()
    sel = pool[good[pool]]
    new_normals[sel] = normals[sel]

    body = document["meshes"][body_index]["primitives"][0]
    attributes = body["attributes"]
    spec = document["accessors"][attributes["POSITION"]]
    added = asset.add_accessor(moved, "VEC3", 34962)
    spec["bufferView"] = document["accessors"][added]["bufferView"]
    spec.pop("byteOffset", None)
    spec["componentType"] = 5126
    spec["type"] = "VEC3"
    spec["count"] = len(moved)

    spec = document["accessors"][attributes["NORMAL"]]
    added = asset.add_accessor(new_normals, "VEC3", 34962)
    spec["bufferView"] = document["accessors"][added]["bufferView"]
    spec.pop("byteOffset", None)
    spec["componentType"] = 5126
    spec["type"] = "VEC3"
    spec["count"] = len(new_normals)

    asset.save(target)
    print("YXZ_POKE pushed %d vertices back, deepest %.3f mm"
          % (int(bad.sum()), push.max() * 1000))
    print("YXZ_POKE wrote %s" % target)


if __name__ == "__main__":
    main()
