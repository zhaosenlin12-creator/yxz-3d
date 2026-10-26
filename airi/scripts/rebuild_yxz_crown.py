"""Rebuild the torn crown of the YXZ helmet as a clean dome.

The scan of the toy came back with the top of the helmet split open.  A
long ragged slit runs most of the way round the crown, and the sheet of
material that the slit let go of stands up off the back of the head like
a pair of horns.  From the front those horns are the whole of the
problem: they break the silhouette of the helmet in two places, and
where the slit is the camera looks straight into the inside of the
helmet, which is a bowl rather than a head.

The helmet is a dome.  Everything above the eyes is very nearly a ball,
and the shell that is still there follows that ball to within a couple
of millimetres, so the missing dome has a shape that is already known:
it is the ball the rest of the helmet sits on, continued over the
opening.  That is what this rebuilds.

It does it in three steps.

* The standing sheet is taken away.  It is a torn edge, not a feature,
  and there is nothing to keep.
* The opening is measured.  The rim of the tear is a closed curve on the
  ball, and the part of the ball it encloses is what has to be filled.
* The fill is a dome on that ball.  It is not a sphere of its own: the
  radius of the ball is read from the shell that survived, at every
  direction, so the new surface continues the helmet's own shape rather
  than imposing a new one, and the helmet's panel lines and star stay
  where they were because the new surface inherits their texture
  coordinates from the shell by direction.

The new dome overlaps the shell it joins by a couple of degrees, so the
torn edge ends up underneath it and cannot be seen, and it is lifted a
fraction of a millimetre off the ball so that it never fights with the
shell for the same pixels.

Usage:
  python scripts/rebuild_yxz_crown.py <source.vrm> <out.vrm> \
    [--margin 3.0] [--lift 0.0004] [--az 2.0] [--elev 1.5] [--report-only]
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb, write_glb  # noqa: E402


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def decode(document, data, index):
    a = document["accessors"][index]
    view = document["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(data, dtype=dtype, count=a["count"] * width,
                         offset=start).reshape(a["count"], width).copy()


def repack(document, binary, replacements):
    """Rebuild the binary chunk, swapping in new blobs where asked."""
    chunks = []
    offset = 0
    for index, view in enumerate(document["bufferViews"]):
        if index in replacements:
            blob = replacements[index]
        else:
            start = view.get("byteOffset", 0)
            blob = binary[start:start + view["byteLength"]]
        padding = (-offset) % 4
        chunks.append(b"\x00" * padding)
        offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        chunks.append(blob)
        offset += len(blob)
    document["buffers"] = [{"byteLength": offset}]
    return b"".join(chunks)


def direction(centre, points):
    v = np.asarray(points, dtype=float) - centre
    return v / np.maximum(np.linalg.norm(v, axis=1), 1e-9)[:, None]


def sphere_fit(points, centre, radius):
    """The ball the head sits in, fitted to the shell that survived."""
    x = np.asarray(points, dtype=float)
    for _ in range(24):
        d = np.linalg.norm(x - centre, axis=1)
        keep = np.abs(d - radius) < 0.012
        if keep.sum() < 32:
            break
        xs = x[keep]
        a = np.c_[2 * xs, np.ones(len(xs))]
        b = (xs ** 2).sum(axis=1)
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        centre = sol[:3]
        radius = float(np.sqrt(max(sol[3] + (centre ** 2).sum(), 1e-6)))
    return centre, radius


def smooth_ring(ring, passes=18, weight=0.30):
    current = np.array(ring, dtype=float)
    for _ in range(passes):
        blended = (current * (1.0 - weight)
                   + (np.roll(current, 1, axis=0) + np.roll(current, -1, axis=0)) * 0.5 * weight)
        current = blended / np.maximum(np.linalg.norm(blended, axis=1), 1e-9)[:, None]
    return current


def order_loop(rim, boundary):
    """Put the rim vertices in the order they go round the tear."""
    adjacency = defaultdict(list)
    for a, b in zip((boundary // 400000).tolist(), (boundary % 400000).tolist()):
        adjacency[a].append(b)
        adjacency[b].append(a)
    if len(adjacency) != len(rim):
        return None
    start = int(rim[0])
    order = [start]
    seen = {start}
    previous = None
    current = start
    while True:
        following = [n for n in adjacency[current] if n != previous and n not in seen]
        if not following:
            break
        previous, current = current, following[0]
        seen.add(current)
        order.append(current)
        if current == start:
            break
    return order if len(order) == len(rim) else None


def radius_field(positions, dirs, dist, crown, az_step, elev_step):
    """The radius of the shell at every direction, on a coarse grid."""
    columns = int(round(360.0 / az_step))
    rows = int(round(180.0 / elev_step))
    grid = np.full((rows, columns), np.nan)
    azimuth = np.degrees(np.arctan2(dirs[:, 2], dirs[:, 0]))
    elevation = np.degrees(np.arcsin(np.clip(dirs[:, 1], -1, 1)))
    column = np.floor((azimuth + 180.0) / az_step).astype(int) % columns
    row = np.clip(((elevation + 90.0) / elev_step).astype(int), 0, rows - 1)
    usable = crown & (dist < 0.46)
    for r, c, d in zip(row[usable], column[usable], dist[usable]):
        if np.isnan(grid[r, c]) or d > grid[r, c]:
            grid[r, c] = d
    for _ in range(60):
        if not np.isnan(grid).any():
            break
        filled = grid.copy()
        for shift_r in (-1, 0, 1):
            for shift_c in (-1, 0, 1):
                if shift_r == 0 and shift_c == 0:
                    continue
                rolled = np.roll(np.roll(grid, shift_r, axis=0), shift_c, axis=1)
                filled = np.where(np.isnan(filled) & ~np.isnan(rolled), rolled, filled)
        grid = filled
    grid = np.nan_to_num(grid, nan=0.32)
    # The dome has to sit outside the shell everywhere, or the shell's
    # torn edge pokes through it.  Smoothing the envelope afterwards
    # keeps it from becoming a set of steps.
    for _ in range(6):
        rolled = grid.copy()
        for shift_r in (-1, 0, 1):
            for shift_c in (-1, 0, 1):
                if shift_r == 0 and shift_c == 0:
                    continue
                rolled = np.maximum(rolled, np.roll(np.roll(grid, shift_r, axis=0), shift_c, axis=1))
        grid = rolled
    for _ in range(8):
        smoothed = np.zeros_like(grid)
        for shift_r in (-1, 0, 1):
            for shift_c in (-1, 0, 1):
                smoothed += np.roll(np.roll(grid, shift_r, axis=0), shift_c, axis=1)
        grid = smoothed / 9.0
    return grid


def sample_field(field, az_step, elev_step, azimuth, elevation, fallback):
    columns = field.shape[1]
    rows = field.shape[0]
    column = int((azimuth + 180.0) // az_step) % columns
    row = min(max(int((elevation + 90.0) // elev_step), 0), rows - 1)
    value = field[row, column]
    if not np.isfinite(value) or value <= 0:
        return fallback
    return float(value)


def nearest_by_direction(dirs, targets, mask=None):
    """For each new vertex, the shell vertex that lies in its direction."""
    if mask is not None:
        dirs = dirs[mask]
    best = np.zeros(len(targets), dtype=np.int64)
    best_dot = np.full(len(targets), -2.0)
    chunk = 4000
    for start in range(0, len(dirs), chunk):
        block = dirs[start:start + chunk]
        dots = targets @ block.T
        which = np.argmax(dots, axis=1)
        value = dots[np.arange(len(targets)), which]
        better = value > best_dot
        best_dot[better] = value[better]
        best[better] = start + which[better]
    if mask is not None:
        indices = np.nonzero(mask)[0]
        best = indices[best]
    return best


def atlas_of(document, binary):
    """The base colour map, as an array of pixels."""
    from PIL import Image
    import io

    material = document["materials"][0]
    texture = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    source = document["textures"][texture].get("source")
    if source is None:
        return None
    image = document["images"][source]
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    blob = binary[start:start + view["byteLength"]]
    return np.asarray(Image.open(io.BytesIO(blob)).convert("RGB"))


def vertex_colours(atlas, uvs):
    """The colour the atlas has at each vertex's texture coordinate."""
    if atlas is None:
        return None
    height, width = atlas.shape[:2]
    x = np.clip((uvs[:, 0] * width).astype(int), 0, width - 1)
    y = np.clip(((1.0 - uvs[:, 1]) * height).astype(int), 0, height - 1)
    return atlas[y, x].astype(int)


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    margin = float(value_after("--margin", "3.0"))
    lift = float(value_after("--lift", "0.0004"))
    az_step = float(value_after("--az", "2.0"))
    elev_step = float(value_after("--elev", "1.5"))
    report_only = "--report-only" in sys.argv

    document, data = read_glb(source)
    primitive = document["meshes"][0]["primitives"][0]
    attributes = primitive["attributes"]
    positions = decode(document, data, attributes["POSITION"]).astype(np.float64)
    normals = decode(document, data, attributes["NORMAL"]).astype(np.float64)
    uvs = decode(document, data, attributes["TEXCOORD_0"]).astype(np.float64)
    joints = decode(document, data, attributes["JOINTS_0"])
    weights = decode(document, data, attributes["WEIGHTS_0"]).astype(np.float64)
    indices = decode(document, data, primitive["indices"]).reshape(-1).astype(np.uint32)
    triangles = indices.reshape(-1, 3)

    centre = np.array([float(part) for part in
                       value_after("--centre", "0,0.06,0.04").split(",")])
    radius = float(value_after("--radius", "0.3193"))
    dirs = direction(centre, positions)
    dist = np.linalg.norm(positions - centre, axis=1)
    outward = (normals * dirs).sum(axis=1)
    if "--fit" in sys.argv:
        picked = ((positions[:, 1] > 0.10) & (dist > radius - 0.05)
                  & (dist < radius + 0.012) & (outward > 0.05))
        centre, radius = sphere_fit(positions[picked], centre, radius)
        dirs = direction(centre, positions)
        dist = np.linalg.norm(positions - centre, axis=1)
        outward = (normals * dirs).sum(axis=1)
    atlas = atlas_of(document, data)
    colours = vertex_colours(atlas, uvs)
    pale = np.ones(len(positions), dtype=bool)
    if colours is not None:
        pale = colours.min(axis=1) > 140
    shell_only = ((outward > 0.25) & (dist > radius - 0.05) & (dist < radius + 0.012)
                  & pale)
    print("YXZ_CROWN ball centre=%s radius=%.4f shellVerts=%d"
          % (centre.round(4), radius, int(shell_only.sum())))

    centroid = positions[triangles].mean(axis=1)
    cdist = np.linalg.norm(centroid - centre, axis=1)
    flap_face = ((cdist > radius + 0.010) & (centroid[:, 1] > 0.12) & (cdist < 0.46))
    print("YXZ_CROWN flapFaces=%d" % int(flap_face.sum()))

    key = np.round(positions, 6)
    lookup = {}
    welded = np.empty(len(positions), dtype=np.int64)
    for i, point in enumerate(map(tuple, key)):
        if point not in lookup:
            lookup[point] = i
        welded[i] = lookup[point]
    face_verts = np.stack([welded[triangles[:, 0]], welded[triangles[:, 1]],
                            welded[triangles[:, 2]]], axis=1)
    edges = []
    for i in range(3):
        a = face_verts[:, i]
        b = face_verts[:, (i + 1) % 3]
        edges.append(np.minimum(a, b) * 400000 + np.maximum(a, b))
    edges = np.concatenate(edges)
    unique, counts = np.unique(edges, return_counts=True)
    boundary = unique[counts == 1]
    rim = np.unique(np.concatenate([boundary // 400000, boundary % 400000]))
    print("YXZ_CROWN rimVertices=%d" % len(rim))

    order = order_loop(rim, boundary)
    if order is None:
        print("YXZ_CROWN no rim loop")
        return
    loop = smooth_ring(dirs[order], passes=18, weight=0.30)
    azimuth = np.degrees(np.arctan2(loop[:, 2], loop[:, 0]))
    elevation = np.degrees(np.arcsin(np.clip(loop[:, 1], -1, 1)))

    columns = int(round(360.0 / az_step))
    floor = np.full(columns, 90.0)
    profile = np.full(columns, 90.0)
    for column in range(columns):
        middle = (column + 0.5) * az_step - 180.0
        delta = np.abs((azimuth - middle + 180.0) % 360.0 - 180.0)
        near = delta < az_step * 0.75
        if near.any():
            profile[column] = elevation[near].min()
    # The tear's rim is not a function of the compass point -- it comes
    # back on itself -- so the profile is read over a window wide enough
    # to catch every part of it, and the dome is then dropped below the
    # lowest of those.  A tear point at any compass point is then under
    # the dome, which is what hides it.
    window = max(1, int(round(4.0 / az_step)))
    padded = np.concatenate([profile, profile, profile])
    lowest = np.min(np.stack([np.roll(padded, shift) for shift in range(-window, window + 1)]),
                     axis=0)[columns:2 * columns]
    floor = np.clip(lowest - margin, -10.0, 88.0)
    print("YXZ_CROWN domeEdge %d..%d mean %.1f"
          % (int(floor.min()), int(floor.max()), float(floor.mean())))

    field = radius_field(positions, dirs, dist, shell_only, az_step, elev_step)

    # Everything the dome covers is put underneath it.  The shell's own
    # torn edge stands a few millimetres proud of the ball in places,
    # and a proud edge shows through the new surface as a flake, so the
    # shell is pulled in to just below the dome everywhere the dome
    # reaches.  This also takes the scan's noise out of the crown.
    keep_vertex = np.zeros(len(positions), dtype=bool)
    keep_vertex[np.unique(triangles[~flap_face])] = True
    azimuth_of = np.degrees(np.arctan2(dirs[:, 2], dirs[:, 0]))
    elevation_of = np.degrees(np.arcsin(np.clip(dirs[:, 1], -1, 1)))
    column_of = np.floor((azimuth_of + 180.0) / az_step).astype(int) % columns
    under = keep_vertex & (dist < 0.46) & (elevation_of > floor[column_of])
    dome_radius = np.array([sample_field(field, az_step, elev_step,
                                         azimuth_of[i], elevation_of[i], radius)
                             for i in np.nonzero(under)[0]])
    target = dome_radius + lift - 0.0005
    moved = np.nonzero(under)[0][dist[under] > target]
    positions[moved] = centre + dirs[moved] * target[dist[under] > target][:, None]
    normals[moved] = dirs[moved]
    print("YXZ_CROWN pulledUnderDome=%d" % len(moved))

    rows = []
    for column in range(columns):
        middle = (column + 0.5) * az_step - 180.0
        top = float(floor[column])
        count = max(1, int(math.ceil((88.0 - top) / elev_step)))
        rows.append((middle, top, count))

    base = len(positions)
    dome_pos = []
    dome_nrm = []
    vertex_of = {}
    for column, (middle, top, count) in enumerate(rows):
        for step in range(count):
            elevation_here = top + (88.0 - top) * (step / max(count - 1, 1))
            a = math.radians(middle)
            b = math.radians(elevation_here)
            u = np.array([math.cos(b) * math.cos(a), math.sin(b),
                          math.cos(b) * math.sin(a)])
            here = sample_field(field, az_step, elev_step, middle, elevation_here, radius)
            dome_pos.append(centre + u * (here + lift))
            dome_nrm.append(u)
            vertex_of[(column, step)] = base + len(dome_pos) - 1
    apex = base + len(dome_pos)
    dome_pos.append(centre + np.array([0.0, 1.0, 0.0]) * (radius + lift))
    dome_nrm.append(np.array([0.0, 1.0, 0.0]))

    dome_index = []
    for column in range(columns):
        nxt = (column + 1) % columns
        count_a = rows[column][2]
        count_b = rows[nxt][2]
        for step in range(min(count_a, count_b) - 1):
            dome_index.append((vertex_of[(column, step)], vertex_of[(column, step + 1)],
                               vertex_of[(nxt, step + 1)]))
            dome_index.append((vertex_of[(column, step)], vertex_of[(nxt, step + 1)],
                               vertex_of[(nxt, step)]))
        dome_index.append((vertex_of[(column, count_a - 1)],
                           vertex_of[(nxt, count_b - 1)], apex))

    sample = nearest_by_direction(dirs, np.array(dome_pos) - centre, shell_only)
    dome_uv = uvs[sample].copy()
    # The texture is picked by direction, and the direction lookup is
    # noisy at this scale, so the coordinates are relaxed across the
    # dome.  Without this the crown wears the texture like static.
    grid_uv = np.full((columns, max(r[2] for r in rows), 2), np.nan)
    for column, (_, _, count) in enumerate(rows):
        for step in range(count):
            grid_uv[column, step] = dome_uv[vertex_of[(column, step)] - base]
    for _ in range(6):
        filled = grid_uv.copy()
        along = np.roll(grid_uv, 1, axis=1)
        along[0] = np.nan
        along[-1] = np.nan
        filled = np.where(np.isnan(filled), along, filled)
        across = np.roll(grid_uv, 1, axis=0)
        filled = np.where(np.isnan(filled), across, filled)
        grid_uv = filled
    for column, (_, _, count) in enumerate(rows):
        for step in range(count):
            value = grid_uv[column, step]
            if np.isfinite(value).all():
                dome_uv[vertex_of[(column, step)] - base] = value
    print("YXZ_CROWN domeVertices=%d domeTriangles=%d" % (len(dome_pos), len(dome_index)))

    if report_only:
        print("YXZ_CROWN report only")
        return

    new_triangles = np.concatenate([triangles[~flap_face],
                                    np.array(dome_index, dtype=np.uint32)])
    position_out = np.concatenate([positions, np.array(dome_pos, dtype=np.float32)])
    normal_out = np.concatenate([normals, np.array(dome_nrm, dtype=np.float32)])
    uv_out = np.concatenate([uvs, dome_uv.astype(np.float32)])
    joint_out = np.concatenate([joints, joints[sample].astype(joints.dtype)])
    weight_out = np.concatenate([weights, weights[sample].astype(np.float32)])
    index_out = new_triangles.reshape(-1).astype(np.uint32)

    replacements = {
        0: position_out.astype("<f4").tobytes(),
        1: normal_out.astype("<f4").tobytes(),
        2: uv_out.astype("<f4").tobytes(),
        3: joint_out.tobytes(),
        4: weight_out.astype("<f4").tobytes(),
        5: index_out.astype("<u4").tobytes(),
    }
    data = repack(document, data, replacements)
    for index in (0, 1, 2, 3, 4):
        document["accessors"][index]["count"] = len(position_out)
    document["accessors"][0]["min"] = position_out.min(axis=0).tolist()
    document["accessors"][0]["max"] = position_out.max(axis=0).tolist()
    document["accessors"][5]["count"] = len(index_out)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, data)
    print("YXZ_CROWN written " + str(output))


if __name__ == "__main__":
    main()
