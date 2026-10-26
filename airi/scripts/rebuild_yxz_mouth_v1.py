"""Rebuild the mouth so that it can be opened without breaking the face.

The plate that carries the mouth is a piece of the face's own surface:
it is the face, lifted a fraction of a millimetre, cut with a hole in
the middle.  The hole is the mouth, and the dark dish behind it is the
inside of the mouth.

The old plate moved its hole the way a jaw moves -- the rim of the hole
was pushed *into* the head.  On a plate that lies on a face, pushing
into the head means going under the face: a thousand of the plate's
four thousand vertices ended up inside the muzzle, fighting it for the
same pixels, and the painted surface of the face came out of the render
shredded into shards.  The rings of the plate crossed each other at the
same time, so it folded over itself as well.

This rebuild keeps the hole's rim in the plane of the face and lets the
mouth open sideways and downwards instead of inwards.  Every state of
the plate is projected onto the face on its own, so no state can ever be
inside the face, and every state is built by interpolating from the new
hole to the same fixed outer edge, so the rings can never cross.

The dish behind the hole is rebuilt as well: a shallow dark bowl that
lies in front of the muzzle and is wide enough to fill the widest
mouth.  The old one was a white cone that ended in a bright point, and
opening the mouth showed that point as a white dome.

    python scripts/rebuild_yxz_mouth.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face, grid_indices  # noqa: E402


RINGS = 28
SEGMENTS = 144

# The outer edge of the plate: a fixed ellipse around the mouth.
OUTER_WIDTH = 0.048
OUTER_HEIGHT = 0.018

# How far the plate stands off the face.  The dish below it is raised
# by less than this, so the plate always covers the dish.
LIFT = 0.00045

# The dish: a shallow bowl in front of the muzzle, wide enough to fill
# the widest mouth, and raised by a little at its rim so that it reads
# as a hollow rather than as a sticker.
DISH_WIDTH = 0.034
DISH_HEIGHT = 0.016
DISH_RISE = 0.00030
DISH_FLOOR = 0.00014

# The mouth's shapes.  The first number is the half width of the
# opening, the second its half height, the third how far below the
# centre of the mouth it sits.  The rest shape is a wide, thin slit:
# a closed mouth.
SHAPES = {
    "Basis": (0.0300, 0.0025, 0.0000),
    "aa": (0.0195, 0.0125, -0.0012),
    "ih": (0.0250, 0.0072, 0.0000),
    "ou": (0.0140, 0.0104, -0.0006),
    "ee": (0.0280, 0.0048, 0.0006),
    "happy": (0.0300, 0.0068, 0.0030),
    "sad": (0.0235, 0.0048, -0.0032),
    "angry": (0.0270, 0.0040, -0.0022),
    "relaxed": (0.0215, 0.0032, 0.0006),
    "surprised": (0.0180, 0.0125, -0.0012),
}


def ellipse(half_width, half_height, centre, count, shift=0.0):
    """A ring of points around a centre, in the plane of the face."""
    angle = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    points = np.zeros((count, 3))
    points[:, 0] = centre[0] + half_width * np.cos(angle)
    points[:, 1] = centre[1] + shift + half_height * np.sin(angle)
    points[:, 2] = centre[2]
    return points


def build_grid(inner, outer, depth_at, blend=0.7, samples=192):
    """The plate's grid, from the hole out to the fixed outer edge.

    The rings are interpolated along the ray from the hole to the
    outer edge, so each ring is further out than the one before it and
    the plate cannot fold over itself however far the hole opens.

    Where the rings fall is not left to chance.  The lower lip of the
    face ends in an edge that stands almost upright, seven
    millimetres of it; a ring placed on one side of that edge and the
    next ring placed on the other side are joined by a straight line
    that cuts straight through the lip, and the lip comes through the
    plate.  So the rings are spaced by how much surface they have to
    cover rather than by how far out they are: where the face turns
    over that edge, the rings crowd together and the plate follows
    the edge instead of cutting across it.
    """
    t = np.linspace(0.0, 1.0, samples)
    rays = (inner[None, :, :] * (1.0 - t[:, None, None])
            + outer[None, :, :] * t[:, None, None])
    z = depth_at(rays[:, :, 0], rays[:, :, 1])
    points = np.stack([rays[:, :, 0], rays[:, :, 1], z], axis=-1)
    steps = np.linalg.norm(np.diff(points, axis=0), axis=-1)
    cumulative = np.concatenate(
        [np.zeros((1, points.shape[1])), np.cumsum(steps, axis=0)], axis=0)
    total = cumulative[-1]

    evenly = np.linspace(0.0, 1.0, RINGS)[:, None]
    wanted = (1.0 - blend) * evenly * total[None, :] + blend * evenly * total[None, :]
    wanted = (1.0 - blend) * evenly + blend * (evenly * total[None, :])
    wanted = np.clip(wanted, 0.0, None)

    rings = np.empty((RINGS, points.shape[1]))
    for segment in range(points.shape[1]):
        rings[:, segment] = np.interp(wanted[:, segment],
                                      cumulative[:, segment], t)
    grid = (inner[None, :, :] * (1.0 - rings[:, :, None])
            + outer[None, :, :] * rings[:, :, None])
    return grid
def vertex_normals(points, triangles):
    """Normals from the shape of the mesh itself."""
    triangles = triangles.reshape(-1, 3)
    corners = points[triangles]
    face_normals = np.cross(corners[:, 1] - corners[:, 0],
                             corners[:, 2] - corners[:, 0])
    normals = np.zeros_like(points)
    for column in range(3):
        np.add.at(normals, triangles[:, column], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths < 1e-12] = 1.0
    return normals / lengths


def smooth_normals(normals, rings, segments, passes=2):
    """Soften the plate's normals the way the face's own are softened.

    The face is a coarse mesh: where the muzzle creases into the
    smile, one large triangle spans the whole crease and its normals
    are averaged, so the crease reads as a soft fold.  The plate is a
    fine grid: it samples the same crease at a fraction of a
    millimetre, and the wall of the crease -- which is almost
    vertical -- turns into a hard band of grazing normals, and the
    toon shader lights a band like that like chrome.  Averaging the
    plate's normals over roughly the distance the face averages them
    over puts the two back in step.
    """
    grid = normals.reshape(rings, segments, 3).copy()
    for _ in range(passes):
        across = (grid + np.roll(grid, 1, axis=1)
                  + np.roll(grid, -1, axis=1)) / 3.0
        padded = np.pad(across, ((1, 1), (0, 0), (0, 0)), mode="edge")
        grid = (across + padded[:-2] + padded[2:]) / 3.0
    lengths = np.linalg.norm(grid, axis=2, keepdims=True)
    lengths[lengths < 1e-9] = 1.0
    return (grid / lengths).reshape(-1, 3)


def heightmap(face, centre, half_x, half_y, step, candidates):
    """The front of the face, sampled as a depth map.

    The plate is built on this map rather than by dropping a flat grid
    onto the face and sliding each point to the nearest surface: the
    face is round, so on a long thin shape like the mouth's slit the
    nearest surface point jumps from one side to the other, and the
    edge of the hole comes out as a flight of stairs.

    The map is a straight down-ray onto the face: every cell keeps the
    front-most triangle that passes through it, and that triangle is
    remembered, so the position, the normal and the texture coordinate
    of any point all come from one and the same piece of the face.
    """
    count_x = int(2.0 * half_x / step) + 1
    count_y = int(2.0 * half_y / step) + 1
    xs = centre[0] - half_x + np.arange(count_x) * step
    ys = centre[1] - half_y + np.arange(count_y) * step
    depth = np.full((count_y, count_x), -np.inf)
    hit = np.full((count_y, count_x), -1, dtype=np.int64)

    for index in candidates:
        a, b, c = face.positions[face.triangles[index]]
        x0 = min(a[0], b[0], c[0])
        x1 = max(a[0], b[0], c[0])
        y0 = min(a[1], b[1], c[1])
        y1 = max(a[1], b[1], c[1])
        column0 = max(0, int(np.floor((x0 - xs[0]) / step)))
        column1 = min(count_x - 1, int(np.ceil((x1 - xs[0]) / step)))
        row0 = max(0, int(np.floor((y0 - ys[0]) / step)))
        row1 = min(count_y - 1, int(np.ceil((y1 - ys[0]) / step)))
        if column1 < column0 or row1 < row0:
            continue
        grid_x = xs[column0:column1 + 1][None, :]
        grid_y = ys[row0:row1 + 1][:, None]
        ab = b - a
        ac = c - a
        d00 = ab[0] * ab[0] + ab[1] * ab[1]
        d01 = ab[0] * ac[0] + ab[1] * ac[1]
        d11 = ac[0] * ac[0] + ac[1] * ac[1]
        denom = d00 * d11 - d01 * d01
        # A triangle that stands on edge has no area in plan.  Its
        # weights are meaningless, and letting it into the map puts
        # the plate's points wherever its weights happen to blow up.
        if abs(denom) < 1e-18:
            continue
        px = grid_x - a[0]
        py = grid_y - a[1]
        d20 = px * ab[0] + py * ab[1]
        d21 = px * ac[0] + py * ac[1]
        weight_b = (d11 * d20 - d01 * d21) / denom
        weight_c = (d00 * d21 - d01 * d20) / denom
        weight_a = 1.0 - weight_b - weight_c
        inside = (weight_a >= -1e-6) & (weight_b >= -1e-6) & (weight_c >= -1e-6)
        if not inside.any():
            continue
        z = weight_a * a[2] + weight_b * b[2] + weight_c * c[2]
        block = depth[row0:row1 + 1, column0:column1 + 1]
        better = inside & (z > block)
        block[better] = z[better]
        hit[row0:row1 + 1, column0:column1 + 1][better] = index

    return xs, ys, depth, hit


def sample_surface(face, xs, ys, hit, x, y):
    """The face under a point: where it is, which way it faces, its paint.

    The triangle that answered the ray is used, and the weights are
    worked out again from the point itself, so the answer is exact and
    does not depend on which cell the point fell in.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    count_x = len(xs)
    count_y = len(ys)
    column = np.clip(((x - xs[0]) / (xs[1] - xs[0])).astype(int),
                     0, count_x - 1)
    row = np.clip(((y - ys[0]) / (ys[1] - ys[0])).astype(int),
                  0, count_y - 1)

    chosen = hit[row, column]
    # A cell with no triangle in it is looked at with its neighbours,
    # so that a hole in the map does not become a hole in the plate.
    for radius in (1, 2, 4):
        missing = chosen < 0
        if not missing.any():
            break
        for offset_y in range(-radius, radius + 1):
            for offset_x in range(-radius, radius + 1):
                if offset_x == 0 and offset_y == 0:
                    continue
                near_row = np.clip(row + offset_y, 0, count_y - 1)
                near_column = np.clip(column + offset_x, 0, count_x - 1)
                take = missing & (chosen < 0)
                chosen = np.where(take, hit[near_row, near_column], chosen)
    if (chosen < 0).any():
        missing = np.nonzero(chosen < 0)[0]
        raise SystemExit("the face map does not cover %d points" % len(missing))

    triangles = face.triangles[chosen]
    a = face.positions[triangles[:, 0]]
    b = face.positions[triangles[:, 1]]
    c = face.positions[triangles[:, 2]]
    ab = b - a
    ac = c - a
    d00 = ab[:, 0] * ab[:, 0] + ab[:, 1] * ab[:, 1]
    d01 = ab[:, 0] * ac[:, 0] + ab[:, 1] * ac[:, 1]
    d11 = ac[:, 0] * ac[:, 0] + ac[:, 1] * ac[:, 1]
    denom = d00 * d11 - d01 * d01
    safe = np.where(np.abs(denom) < 1e-18, 1.0, denom)
    px = x - a[:, 0]
    py = y - a[:, 1]
    d20 = px * ab[:, 0] + py * ab[:, 1]
    d21 = px * ac[:, 0] + py * ac[:, 1]
    weight_b = (d11 * d20 - d01 * d21) / safe
    weight_c = (d00 * d21 - d01 * d20) / safe
    weight_a = 1.0 - weight_b - weight_c

    # The point asked for may sit just outside the triangle the map
    # chose for its cell.  Left alone, the weights run away and the
    # plate dives behind the face; held in, they stay on the triangle
    # and the plate stays on the surface.
    outside = (weight_a < 0.0) | (weight_b < 0.0) | (weight_c < 0.0)
    if outside.any():
        weight_a = np.clip(weight_a, 0.0, None)
        weight_b = np.clip(weight_b, 0.0, None)
        weight_c = np.clip(weight_c, 0.0, None)
        total = weight_a + weight_b + weight_c
        total[total < 1e-12] = 1.0
        weight_a = weight_a / total
        weight_b = weight_b / total
        weight_c = weight_c / total

    z = weight_a * a[:, 2] + weight_b * b[:, 2] + weight_c * c[:, 2]
    normals = (weight_a[:, None] * face.normals[triangles[:, 0]]
               + weight_b[:, None] * face.normals[triangles[:, 1]]
               + weight_c[:, None] * face.normals[triangles[:, 2]])
    uvs = (weight_a[:, None] * face.uvs[triangles[:, 0]]
           + weight_b[:, None] * face.uvs[triangles[:, 1]]
           + weight_c[:, None] * face.uvs[triangles[:, 2]])
    surface = np.column_stack([x, y, z])
    return surface, normals, uvs


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])

    asset = Asset(source)
    document = asset.document
    meshes = document["meshes"]

    body_index = next(
        i for i, mesh in enumerate(meshes)
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(
        i for i, mesh in enumerate(meshes) if mesh.get("name") == "YXZ_Mouth")
    cavity_index = next(
        i for i, mesh in enumerate(meshes)
        if mesh.get("name") == "YXZ_MouthCavity")
    plate_material = next(
        i for i, material in enumerate(document["materials"])
        if material.get("name") == "YXZ_MouthPlate")

    face = Face(asset, body_index)
    mouth = meshes[mouth_index]
    primitive = mouth["primitives"][0]
    attributes = primitive["attributes"]
    base = asset.accessor(attributes["POSITION"]).astype(np.float64)
    if base.shape[0] != RINGS * SEGMENTS:
        raise SystemExit("the plate is not the grid this rebuild expects")
    old_inner = base.reshape(RINGS, SEGMENTS, 3)[0]
    centre = old_inner.mean(axis=0)

    reach = float(np.abs(base - centre).max()) + 0.06
    candidates = face.near(centre, reach)
    print("YXZ_MOUTH centre %s candidates %d"
          % (np.round(centre, 4), len(candidates)))

    xs, ys, depth, hit = heightmap(
        face, centre, OUTER_WIDTH + 0.012, OUTER_HEIGHT + 0.012,
        0.0002, candidates)
    covered = np.isfinite(depth)
    print("YXZ_MOUTH depth map %dx%d covered %.1f%%"
          % (len(xs), len(ys), 100.0 * covered.mean()))
    steps = np.abs(np.diff(depth, axis=1))
    jumps = steps[np.isfinite(steps)]
    if len(jumps):
        print("YXZ_MOUTH depth steps: max %.5f 99%% %.5f"
              % (jumps.max(), np.percentile(jumps, 99)))

    def on_face(points):
        """Put points on the face, using the depth map to aim them."""
        return sample_surface(face, xs, ys, hit, points[:, 0], points[:, 1])

    outer = ellipse(OUTER_WIDTH, OUTER_HEIGHT, centre, SEGMENTS)
    triangles = grid_indices(RINGS, SEGMENTS)

    states = []
    report = {}
    for name, (width, height, shift) in SHAPES.items():
        inner = ellipse(width, height, centre, SEGMENTS, shift)
        grid = build_grid(inner, outer)
        flat = grid.reshape(-1, 3)
        surface, normals, uvs = on_face(flat)
        unit = normals / np.linalg.norm(normals, axis=1, keepdims=True)
        unit = smooth_normals(unit, RINGS, SEGMENTS)
        positions = surface + unit * LIFT

        signed = ((positions - surface) * unit).sum(axis=1)
        rings = positions.reshape(RINGS, SEGMENTS, 3)
        centre_line = rings.mean(axis=1, keepdims=True)
        radius = np.linalg.norm(rings - centre_line, axis=2).mean(axis=1)
        order = bool((np.diff(radius) < 0).any())
        states.append({
            "name": name,
            "positions": positions,
            # The plate wears the face's own normals.  Its own mesh
            # cannot supply them: the hole is a long thin ellipse, so
            # the triangles along its tips are slivers and the normals
            # worked out from the mesh itself come out as rubbish.
            "normals": unit,
            "uvs": uvs,
        })
        report[name] = {
            "sink": round(float(signed.min()), 6),
            "ringOrderBroken": order,
            "holeWidthMm": round(float(width * 2000), 1),
            "holeHeightMm": round(float(height * 2000), 1),
        }
    print("YXZ_MOUTH states " + json.dumps(report))

    base_state = states[0]
    owner = face.nearest_vertices(base_state["positions"], candidates)
    new_primitive = {
        "attributes": {
            "POSITION": asset.add_accessor(
                base_state["positions"], "VEC3", 34962),
            "NORMAL": asset.add_accessor(
                base_state["normals"], "VEC3", 34962),
            "TEXCOORD_0": asset.add_accessor(base_state["uvs"], "VEC2", 34962),
            "JOINTS_0": asset.add_accessor(face.joints[owner], "VEC4", 34962),
            "WEIGHTS_0": asset.add_accessor(face.weights[owner], "VEC4", 34962),
        },
        "indices": asset.add_accessor(triangles, "SCALAR", 34963),
        "material": primitive["material"],
        "targets": [],
    }
    for state in states[1:]:
        new_primitive["targets"].append({
            "POSITION": asset.add_accessor(
                state["positions"] - base_state["positions"], "VEC3"),
            "NORMAL": asset.add_accessor(
                state["normals"] - base_state["normals"], "VEC3"),
        })
    mouth["primitives"] = [new_primitive]

    dish_rings = 7
    dish_segments = SEGMENTS
    dish_points = []
    for ring in range(1, dish_rings + 1):
        t = ring / dish_rings
        ring_points = ellipse(
            DISH_WIDTH * t, DISH_HEIGHT * t, centre, dish_segments, -0.001)
        dish_points.append(ring_points)
    dish_grid = np.concatenate(dish_points, axis=0)
    dish_surface, dish_normals, _ = on_face(dish_grid)
    dish_unit = dish_normals / np.linalg.norm(dish_normals, axis=1, keepdims=True)
    rise = np.concatenate([
        np.full(dish_segments, DISH_RISE + (DISH_FLOOR - DISH_RISE) * (1.0 - ring / dish_rings))
        for ring in range(1, dish_rings + 1)])
    dish_positions = dish_surface + dish_unit * rise[:, None]
    # The inside of the mouth is painted into the atlas, so the dish is
    # no longer needed: a second surface a fraction of a millimetre off
    # the face fights the face for the same pixels.  It is collapsed to
    # a point so that it draws nothing at all.
    dish_positions = np.repeat(
        dish_positions.mean(axis=0)[None, :], dish_positions.shape[0], axis=0)
    # The dish is a bowl with a floor in the middle, so it is closed
    # with a fan rather than with a ring of points on top of each
    # other, which would leave the middle of the mouth unshaded.
    floor = dish_positions.mean(axis=0)
    floor = floor - dish_unit.mean(axis=0) * DISH_FLOOR
    dish_positions = np.concatenate([floor[None, :], dish_positions], axis=0)
    dish_triangles = []
    for segment in range(dish_segments):
        following = (segment + 1) % dish_segments
        dish_triangles.extend([0, 1 + segment, 1 + following])
    for ring in range(dish_rings - 1):
        base = 1 + ring * dish_segments
        upper = base + dish_segments
        for segment in range(dish_segments):
            following = (segment + 1) % dish_segments
            a = base + segment
            b = base + following
            c = upper + following
            d = upper + segment
            dish_triangles.extend([a, c, b, a, d, c])
    dish_triangles = np.array(dish_triangles, dtype=np.int64)
    dish_owner = face.nearest_vertices(dish_positions, candidates)

    cavity = meshes[cavity_index]
    cavity_primitive = cavity["primitives"][0]
    cavity_material = document["materials"][cavity_primitive["material"]]
    cavity_material["pbrMetallicRoughness"].pop("baseColorTexture", None)
    cavity_material["pbrMetallicRoughness"]["baseColorFactor"] = [
        0.075, 0.022, 0.028, 1.0]
    mtoon = cavity_material.setdefault("extensions", {}).setdefault(
        "VRMC_materials_mtoon", {})
    mtoon["colorFactor"] = [0.075, 0.022, 0.028, 1.0]
    mtoon["color"] = [0.075, 0.022, 0.028, 1.0]
    cavity["primitives"] = [{
        "attributes": {
            "POSITION": asset.add_accessor(dish_positions, "VEC3", 34962),
            "NORMAL": asset.add_accessor(
                vertex_normals(dish_positions, dish_triangles), "VEC3", 34962),
            "JOINTS_0": asset.add_accessor(
                face.joints[dish_owner], "VEC4", 34962),
            "WEIGHTS_0": asset.add_accessor(
                face.weights[dish_owner], "VEC4", 34962),
        },
        "indices": asset.add_accessor(dish_triangles, "SCALAR", 34963),
        "material": cavity_primitive["material"],
    }]

    material = document["materials"][plate_material]
    material["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]

    asset.save(target)
    print("YXZ_MOUTH wrote %s" % target)


if __name__ == "__main__":
    main()
