"""Give the mouth an inside.

The plate that carries the mouth is a sheet of the face's own surface
with a hole in it, and the hole is where the mouth opens.  What showed
through that hole used to be the face itself: the muzzle is a mound, so
an open mouth showed the top of the mound, white and round, like a
bubble sitting in the middle of the lips.

So the muzzle is hollowed out and a dark lining is put inside it.  The
face around the mouth is pushed back into a shallow bowl, a lining is
fitted just inside that bowl, and the lining is dark the way the inside
of a mouth is dark -- in its own colour rather than in the colour the
face uses for the shadows it cannot see.

The plate still lies on the surface the face had before the bowl was
cut, and it still wears the face's own paint, so from the front it is
invisible: the mouth is a hole in a sheet of skin, and what shows
through the hole is the inside of the mouth.

    python scripts/finish_yxz_mouth.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face  # noqa: E402
from rebuild_yxz_mouth import heightmap  # noqa: E402


# The mouth's centre on the face.
CENTRE = np.array([0.0, 0.0621, 0.2501])

# The colour of the inside of a mouth: near black at the back, a warm
# dark red where the light still reaches it.
MOUTH_DEEP = np.array([26, 7, 10], dtype=np.float64)
MOUTH_INK = np.array([54, 15, 20], dtype=np.float64)

# The bowl that is cut into the muzzle.  Its size is the size of the
# plate that covers it, so the rim of the bowl is always hidden under
# the plate, and its depth is deep enough that the muzzle's mound
# cannot come back up through the hole.
BOWL_WIDTH = 0.048
BOWL_HEIGHT = 0.021
BOWL_DEPTH = 0.0100
BOWL_FLAT = 0.60
BOWL_FADE = 0.28

# The lining: a copy of the plate, three millimetres behind it, with
# the hole in the plate filled in.  It is built from the plate's own
# surface rather than from the face's, because the plate's surface is
# what the lining has to stay behind.
LINING_WIDTH = 0.034
LINING_HEIGHT = 0.013
LINING_RINGS = 14
LINING_SEGMENTS = 288
# How far behind the plate the lining sits.  It is almost nothing in the
# middle, so that the closed mouth is a line rather than a hole, and it
# grows towards the rim, so that an open mouth has somewhere to go.
#
# The clearance cannot be almost nothing.  The lining is built by
# interpolating the plate's own rim between the angles, and the rim is
# not flat, so the lining lands very close to the plate at the one
# point where the interpolated height happens to be higher than the
# rim's real height there.  Measured over the rim, the closest the two
# surfaces came was seventy microns -- close enough that the depth
# buffer cannot decide between them, and a fight between two surfaces
# a hair apart is a scatter of bright specks along the lips.  A
# millimetre of clearance is more than any depth buffer needs and is
# still invisible: the mouth is a line either way.
LINING_CLEARANCE = 0.0007
LINING_RISE = 0.0025

# The plate's own grid: how many points around it and how many rings.
LINING_PLATE_RINGS = 28
LINING_PLATE_SEGMENTS = 144

# How far clear of the plate a vertex has to be before it is left alone.
CLEARANCE = 0.00006
EXTRA = 0.00004
LIMIT = 0.0040


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def bowl_depth(radius):
    """How far back the muzzle is pushed, at a given distance from the mouth.

    The bowl is flat in the middle and eases back to the face at its
    rim, so that the plate -- which lies on the surface the face had
    before the bowl was cut -- meets the face again at its own edge.
    """
    fade = 1.0 - smoothstep((radius - BOWL_FLAT) / BOWL_FADE)
    return BOWL_DEPTH * fade


def plate_height(points, plate, indices):
    """How far forward the plate is at each point, straight down."""
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
    return summed / np.maximum(lengths, 1e-20), good


def build_lining(face, plate, indices, centre):
    """The dark bowl that lines the hollowed muzzle.

    The lining is a copy of the plate, a few millimetres behind it and
    with the plate's own hole filled in.  It is built from the plate's
    surface because that is the surface it has to stay behind: the face
    turns over a steep edge at the lower lip, and there the plate cuts
    across the edge while the face does not.
    """
    ring = plate[:indices.shape[1]] if False else None
    segments = int(indices.max()) + 1
    # The plate's grid: the first ring is the rim of its hole.
    grid = plate.reshape(LINING_PLATE_RINGS, LINING_PLATE_SEGMENTS, 3)

    def plate_z(x, y, fallback):
        """The plate's own height at a point, and the hole rim's if it
        falls inside the hole."""
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
        px = x[:, None]
        py = y[:, None]
        d20 = (px - a[None, :, 0]) * ab[None, :, 0] \
            + (py - a[None, :, 1]) * ab[None, :, 1]
        d21 = (px - a[None, :, 0]) * ac[None, :, 0] \
            + (py - a[None, :, 1]) * ac[None, :, 1]
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
        rows = np.arange(len(x))
        found = z[rows, best]
        # The hole is a long thin ellipse, so a point inside it cannot
        # be placed on the rim by the angle it makes with the centre:
        # every point along the slit has the same angle as one end of
        # it.  The ellipse's own parameter is what puts a point on the
        # rim it belongs to.
        #
        # The rim's height is then read along that parameter, and it has
        # to be read as the *lowest* rim point near it rather than the
        # rim point at that index.  The rim's points are not evenly
        # spaced in the ellipse's parameter -- they crowd at the ends
        # of the slit -- so the index that the parameter gives is not
        # always the index that is there, and reading the height off it
        # puts the lining in front of the lip by a few tenths of a
        # millimetre.  Where the lining is in front of the lip the two
        # surfaces fight for the same pixels, and the fight shows up as
        # a scatter of bright specks along the mouth.
        #
        # Taking the lowest point in a small window instead puts the
        # lining behind the lip everywhere, whatever the spacing does,
        # and costs a little depth where the lip is highest.
        half_width = max(abs(grid[0][:, 0] - centre[0]).max(), 1e-6)
        half_height = max(abs(grid[0][:, 1] - centre[1]).max(), 1e-6)
        angle = np.mod(np.arctan2((y - centre[1]) / half_height,
                                  (x - centre[0]) / half_width), 2.0 * np.pi)
        rim_z = grid[0][:, 2]
        window = 1
        low = np.array([
            rim_z[max(0, index - window):index + window + 1].min()
            for index in range(len(rim_z))
        ])
        rim = np.interp(angle, np.linspace(0.0, 2.0 * np.pi,
                                          LINING_PLATE_SEGMENTS + 1),
                        np.concatenate([low, low[:1]]))
        return np.where(np.isfinite(found), found, rim), np.isfinite(found)

    angle = np.linspace(0.0, 2.0 * np.pi, LINING_SEGMENTS, endpoint=False)
    rings = []
    for step in range(LINING_RINGS + 1):
        radius = 1.0 - step / LINING_RINGS
        x = centre[0] + LINING_WIDTH * radius * np.cos(angle)
        y = centre[1] + LINING_HEIGHT * radius * np.sin(angle)
        z, _ = plate_z(x, y, None)
        clearance = LINING_CLEARANCE + LINING_RISE * radius ** 2
        rings.append(np.column_stack([x, y, z - clearance]))
    points = np.concatenate(rings, axis=0)

    floor = np.array([[centre[0], centre[1],
                       rings[-1][:, 2].mean() - 0.0008]])
    points = np.concatenate([floor, points], axis=0)

    triangles = []
    for segment in range(LINING_SEGMENTS):
        following = (segment + 1) % LINING_SEGMENTS
        triangles.extend([0, 1 + segment, 1 + following])
    for ring_index in range(LINING_RINGS):
        lower = 1 + ring_index * LINING_SEGMENTS
        upper = lower + LINING_SEGMENTS
        for segment in range(LINING_SEGMENTS):
            following = (segment + 1) % LINING_SEGMENTS
            a = lower + segment
            b = lower + following
            c = upper + following
            d = upper + segment
            triangles.extend([a, c, b, a, d, c])
    return points, np.array(triangles, dtype=np.int64), points


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
    cavity_index = next(
        i for i, mesh in enumerate(document["meshes"])
        if mesh.get("name") == "YXZ_MouthCavity")

    face = Face(asset, body_index)
    surface = face.positions.copy()
    positions = surface.copy()

    candidates = face.near(CENTRE, 0.09)

    # --- the bowl ------------------------------------------------------
    nx = (surface[:, 0] - CENTRE[0]) / BOWL_WIDTH
    ny = (surface[:, 1] - CENTRE[1]) / BOWL_HEIGHT
    radius = np.sqrt(nx * nx + ny * ny)
    depth = bowl_depth(radius)
    print("YXZ_FINISH hollowing the muzzle: %d vertices, deepest %.2f mm"
          % (int((depth > 0).sum()), depth.max() * 1000))
    positions[:, 2] -= depth

    # --- the plate -----------------------------------------------------
    primitive = document["meshes"][mouth_index]["primitives"][0]
    plate = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    indices = asset.accessor(primitive["indices"]).reshape(-1, 3).astype(np.int64)

    pool = np.unique(face.triangles[candidates].reshape(-1))
    points = positions[pool]
    height, covered = plate_height(points, plate, indices)
    poke = np.full(len(pool), -np.inf)
    poke[covered] = points[covered, 2] - height[covered]
    bad = poke > CLEARANCE
    push = np.zeros(len(pool))
    push[bad] = np.minimum(poke[bad] + EXTRA, LIMIT)
    if bad.any():
        positions[pool, 2] -= push
        positions[pool, 1] -= push * 0.25
        print("YXZ_FINISH pushed %d vertices back, deepest %.3f mm"
              % (int(bad.sum()), push.max() * 1000))

    touched = pool[depth[pool] > 0]
    if bad.any():
        touched = np.union1d(touched, pool[bad])
    normals, good = face_normals(positions, face.triangles, touched)
    new_normals = face.normals.copy()
    sel = touched[good[touched]]
    new_normals[sel] = normals[sel]

    body = document["meshes"][body_index]["primitives"][0]
    attributes = body["attributes"]
    for name, values in (("POSITION", positions), ("NORMAL", new_normals)):
        spec = document["accessors"][attributes[name]]
        added = asset.add_accessor(values, "VEC3", 34962)
        spec["bufferView"] = document["accessors"][added]["bufferView"]
        spec.pop("byteOffset", None)
        spec["componentType"] = 5126
        spec["type"] = "VEC3"
        spec["count"] = len(values)

    # --- the lining ----------------------------------------------------
    lining, lining_triangles, lining_grid = build_lining(
        face, plate, indices, CENTRE)
    owner = face.nearest_vertices(lining, candidates)
    lining_normals = face_normals(lining, lining_triangles.reshape(-1, 3),
                                  np.arange(len(lining)))[0]
    print("YXZ_FINISH lining: %d points, %d triangles, rim at z %.4f"
          % (len(lining), len(lining_triangles), lining_grid[:, 2].max()))

    cavity = document["meshes"][cavity_index]
    cavity_primitive = cavity["primitives"][0]
    material = document["materials"][cavity_primitive["material"]]
    material["doubleSided"] = True
    material["pbrMetallicRoughness"]["baseColorFactor"] = [
        float(MOUTH_INK[0] / 255.0), float(MOUTH_INK[1] / 255.0),
        float(MOUTH_INK[2] / 255.0), 1.0]
    mtoon = material.setdefault("extensions", {}).setdefault(
        "VRMC_materials_mtoon", {})
    mtoon["colorFactor"] = [
        float(MOUTH_INK[0] / 255.0), float(MOUTH_INK[1] / 255.0),
        float(MOUTH_INK[2] / 255.0), 1.0]
    mtoon["color"] = list(mtoon["colorFactor"])
    # The shade colour is what a surface shows when it is turned away
    # from the light.  The inside of a mouth is turned away from the
    # light the whole time, so its shade colour has to be the colour of
    # the inside of a mouth and not the colour of the face's shadows.
    mtoon["shadeColorFactor"] = [
        float(MOUTH_DEEP[0] / 255.0), float(MOUTH_DEEP[1] / 255.0),
        float(MOUTH_DEEP[2] / 255.0), 1.0]
    mtoon["rimLightingMixFactor"] = 0.0
    mtoon["parametricRimColorFactor"] = [0.0, 0.0, 0.0]

    cavity["primitives"] = [{
        "attributes": {
            "POSITION": asset.add_accessor(lining, "VEC3", 34962),
            "NORMAL": asset.add_accessor(lining_normals, "VEC3", 34962),
            "TEXCOORD_0": asset.add_accessor(
                np.zeros((len(lining), 2)), "VEC2", 34962),
            "JOINTS_0": asset.add_accessor(face.joints[owner], "VEC4", 34962),
            "WEIGHTS_0": asset.add_accessor(face.weights[owner], "VEC4", 34962),
        },
        "indices": asset.add_accessor(lining_triangles, "SCALAR", 34963),
        "material": cavity_primitive["material"],
    }]

    asset.save(target)
    print("YXZ_FINISH wrote %s" % target)


if __name__ == "__main__":
    main()
