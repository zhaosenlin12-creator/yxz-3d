"""Rebuild the torn crown of the YXZ helmet.

The scan came back with the top of the head torn open.  A ragged seam
goes all the way round the head above the brow, the sheet above the
seam has peeled away and stands up off the back of the crown, and the
top of the helmet is simply not there any more.  Seen from the front
that reads as a broken head rather than a model.

The helmet is a ball.  The shell that survived follows that ball to
within a couple of millimetres, so the missing piece has a shape that
is already known: it is the ball the rest of the helmet sits on,
continued over the opening.

So the repair works from the seam outwards.

* The seam is found from the mesh itself: the boundary of the shell is
  a closed loop, and the loop's height at each compass point says how
  far down the tear reaches there.
* The loop's height is turned into a smooth curve that stays under
  the tear everywhere, and every scrap of head above that curve is
  taken away, so the loose sheet and the torn edge both go.
* A new dome is built on the ball over the opening, from that curve up
  to the top.  The dome's radius at every direction is read from the
  shell that survived, so it continues the helmet's own shape instead
  of imposing a new one, and it is lifted a fraction of a millimetre
  so that it never fights with the shell for the same pixels.
* The shell is pulled in very slightly where it meets the dome, so
  that the last of the scan's noise cannot push through as a flake.

Usage:
  python scripts/rebuild_yxz_crown2.py <source.vrm> <out.vrm> \
    [--margin 2.0] [--lift 0.0003] [--az 2.0] [--report-only]
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
    count = a["count"] * width
    return np.frombuffer(data, dtype=dtype, count=count, offset=start).reshape(a["count"], width).copy()


def repack(document, binary, replacements):
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


def unit(vectors):
    v = np.asarray(vectors, dtype=float)
    return v / np.maximum(np.linalg.norm(v, axis=1), 1e-9)[:, None]


def fit_ball(points, centre, radius, rounds=30, band=0.02):
    x = np.asarray(points, dtype=float)
    for _ in range(rounds):
        xs = x
        a = np.c_[2 * xs, np.ones(len(xs))]
        b = (xs ** 2).sum(axis=1)
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        centre = sol[:3]
        radius = float(np.sqrt(max(sol[3] + (centre ** 2).sum(), 1e-6)))
    return centre, radius


def order_loop(rim, boundary):
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


def rolling_min(values, radius):
    padded = np.concatenate([values, values, values])
    stack = [np.roll(padded, shift) for shift in range(-radius, radius + 1)]
    return np.min(np.stack(stack), axis=0)[len(values):2 * len(values)]


def rolling_mean(values, radius):
    padded = np.concatenate([values, values, values])
    stack = [np.roll(padded, shift) for shift in range(-radius, radius + 1)]
    return np.mean(np.stack(stack), axis=0)[len(values):2 * len(values)]


def nearest_by_direction(dirs, targets, mask):
    """For each new vertex, the shell vertex that lies in its direction."""
    picked = dirs[mask]
    indices = np.nonzero(mask)[0]
    best = np.zeros(len(targets), dtype=np.int64)
    best_dot = np.full(len(targets), -2.0)
    for start in range(0, len(picked), 4000):
        block = picked[start:start + 4000]
        dots = targets @ block.T
        which = np.argmax(dots, axis=1)
        value = dots[np.arange(len(targets)), which]
        better = value > best_dot
        best_dot[better] = value[better]
        best[better] = start + which[better]
    return indices[best]


def atlas_of(document, binary):
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


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    margin = float(value_after("--margin", "2.0"))
    lift = float(value_after("--lift", "0.0003"))
    az_step = float(value_after("--az", "2.0"))
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

    centre = np.array([float(part) for part in value_after("--centre", "0,0.064,0").split(",")])
    radius = float(value_after("--radius", "0.3193"))

    v = positions - centre
    dist = np.linalg.norm(v, axis=1)
    dirs = unit(v)
    elevation = np.degrees(np.arcsin(np.clip(dirs[:, 1], -1, 1)))
    if "--fit" in sys.argv:
        side = (elevation > -20) & (elevation < 25) & (dist < radius + 0.05)
        side = side & (positions[:, 1] > -0.16)
        middle = float(np.median(dist[side]))
        side = side & (np.abs(dist - middle) < 0.012)
        centre, radius = fit_ball(positions[side], centre, radius, rounds=4)
    print("YXZ2 ball centre=%s radius=%.4f" % (centre.round(4), radius))

    v = positions - centre
    dist = np.linalg.norm(v, axis=1)
    dirs = unit(v)
    azimuth = np.degrees(np.arctan2(dirs[:, 2], dirs[:, 0]))
    elevation = np.degrees(np.arcsin(np.clip(dirs[:, 1], -1, 1)))
    outward = (normals * dirs).sum(axis=1)

    key = np.round(positions, 6)
    lookup = {}
    welded = np.empty(len(positions), dtype=np.int64)
    for i, point in enumerate(map(tuple, key)):
        if point not in lookup:
            lookup[point] = i
        welded[i] = lookup[point]
    face_verts = np.stack([welded[triangles[:, 0]], welded[triangles[:, 1]], welded[triangles[:, 2]]], axis=1)
    edges = []
    for i in range(3):
        a = face_verts[:, i]
        b = face_verts[:, (i + 1) % 3]
        edges.append(np.minimum(a, b) * 400000 + np.maximum(a, b))
    edges = np.concatenate(edges)
    unique, counts = np.unique(edges, return_counts=True)
    boundary = unique[counts == 1]
    rim = np.unique(np.concatenate([boundary // 400000, boundary % 400000]))
    order = order_loop(rim, boundary)
    if order is None:
        print("YXZ2 no rim loop")
        return
    print("YXZ2 rimVertices=%d" % len(order))

    columns = int(round(360.0 / az_step))
    column_of = np.floor((azimuth + 180.0) / az_step).astype(int) % columns
    centroid = positions[triangles].mean(axis=1)
    cdist = np.linalg.norm(centroid - centre, axis=1)
    c_dirs = unit(centroid - centre)
    c_el = np.degrees(np.arcsin(np.clip(c_dirs[:, 1], -1, 1)))
    c_az = np.degrees(np.arctan2(c_dirs[:, 2], c_dirs[:, 0]))
    c_col = np.floor((c_az + 180.0) / az_step).astype(int) % columns

    # The sheet that was peeled off the crown has its back to the sky
    # now, and it stands off the ball it came from.  Both are signs of
    # the same thing, and both go.
    tri_normal = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                           positions[triangles[:, 2]] - positions[triangles[:, 0]])
    tri_normal = unit(tri_normal)
    face_out = (tri_normal * c_dirs).sum(axis=1)
    flipped = (c_el > 24) & (cdist < radius + 0.05) & (face_out < 0.0)
    lifted = (c_el > 24) & (cdist > radius + 0.008)
    doomed = flipped | lifted
    print("YXZ2 flipped=%d lifted=%d" % (int(flipped.sum()), int(lifted.sum())))

    # Where is the shell still whole?  The crown is measured on a coarse
    # grid of compass point and height, and the first height at which
    # the shell has gone is the height at which the new dome has to
    # start.
    cell = 2.0
    ncol = int(360.0 / cell)
    nrow = int(180.0 / cell)
    grid_rows = np.clip(((elevation + 90.0) / cell).astype(int), 0, nrow - 1)
    grid_cols = ((azimuth + 180.0) % 360.0 / cell).astype(int) % ncol
    alive = np.zeros((nrow, ncol), dtype=bool)
    kept_faces = triangles[~doomed]
    for pick in (kept_faces[:, 0], kept_faces[:, 1], kept_faces[:, 2]):
        alive[grid_rows[pick], grid_cols[pick]] = True
    crow = np.clip(((c_el + 90.0) / cell).astype(int), 0, nrow - 1)
    ccol = ((c_az + 180.0) % 360.0 / cell).astype(int) % ncol
    alive[crow[~doomed], ccol[~doomed]] = True
    for _ in range(2):
        grown = alive.copy()
        for sr in (-1, 0, 1):
            for sc in (-1, 0, 1):
                grown |= np.roll(np.roll(alive, sr, axis=0), sc, axis=1)
        alive = grown
    first_gap = np.full(ncol, 90.0)
    for col in range(ncol):
        for row in range(nrow):
            here = (row + 0.5) * cell - 90.0
            if here < 20.0:
                continue
            if not alive[row, col]:
                first_gap[col] = here
                break
    window = max(1, int(round(8.0 / cell)))
    floor = rolling_min(first_gap, window)
    smooth = rolling_mean(floor, window)
    cut = np.minimum(smooth, floor - margin)
    cut = np.clip(cut, 28.0, 84.0)
    cut = np.interp(np.arange(columns), np.arange(ncol) * ncol / columns, cut)
    print("YXZ2 cut %d..%d mean %.1f" % (int(cut.min()), int(cut.max()), float(cut.mean())))

    above = c_el > cut[c_col]
    doomed = doomed | above
    print("YXZ2 doomedFaces=%d of %d" % (int(doomed.sum()), len(triangles)))

    keep_vertex = np.zeros(len(positions), dtype=bool)
    keep_vertex[np.unique(triangles[~doomed])] = True

    # How far out the shell is, at every compass point and height.  The
    # helmet is very nearly a ball, so this reads as a smooth surface
    # rather than as the scan's noise, and it is the surface the new
    # dome continues.
    rows = int(round(180.0 / az_step))
    row_of = np.clip(((elevation + 90.0) / az_step).astype(int), 0, rows - 1)
    shell = keep_vertex & (dist < radius + 0.06) & (elevation > 16)
    profile = np.full((rows, columns), np.nan)
    for r, c, d in zip(row_of[shell], column_of[shell], dist[shell]):
        if np.isnan(profile[r, c]) or d > profile[r, c]:
            profile[r, c] = d
    for _ in range(40):
        if not np.isnan(profile).any():
            break
        filled = profile.copy()
        for sr in (-1, 0, 1):
            for sc in (-1, 0, 1):
                if sr == 0 and sc == 0:
                    continue
                rolled = np.roll(np.roll(profile, sr, axis=0), sc, axis=1)
                filled = np.where(np.isnan(filled) & ~np.isnan(rolled), rolled, filled)
        profile = filled
    print("YXZ2 rawProfile %.3f..%.3f nan=%d" % (np.nanmax(profile), np.nanmin(profile), int(np.isnan(profile).sum())))
    profile = np.nan_to_num(profile, nan=radius)
    # Above the seam the shell is gone, so the ball carries on at the
    # radius it had at the seam.
    for column in range(columns):
        seam_row = int((cut[column] + 90.0) / az_step)
        seam_row = int(min(max(seam_row, 0), rows - 1))
        profile[seam_row:, column] = profile[seam_row, column]
    for _ in range(3):
        smoothed = np.zeros_like(profile)
        for sr in (-1, 0, 1):
            smoothed += np.roll(profile, sr, axis=0)
        profile = smoothed / 3.0
    profile = np.maximum(profile, radius - 0.004)
    print("YXZ2 profile %.3f..%.3f" % (profile.min(), profile.max()))

    def profile_at(az_list, el_list):
        a = np.asarray(az_list)
        e = np.asarray(el_list)
        fr = (e + 90.0) / az_step - 0.5
        fc = (a + 180.0) / az_step - 0.5
        r0 = np.clip(np.floor(fr).astype(int), 0, rows - 2)
        c0 = np.clip(np.floor(fc).astype(int), 0, columns - 2)
        tr = np.clip(fr - r0, 0.0, 1.0)
        tc = np.clip(fc - c0, 0.0, 1.0)
        low = profile[r0, c0] * (1 - tc) + profile[r0, c0 + 1] * tc
        high = profile[r0 + 1, c0] * (1 - tc) + profile[r0 + 1, c0 + 1] * tc
        return low * (1 - tr) + high * tr

    band = 16.0
    in_band = keep_vertex & (dist < 0.46)
    in_band = in_band & (elevation > cut[column_of] - band)
    target = profile_at(azimuth, elevation) + lift - 0.0004
    pulled = np.nonzero(in_band & (dist > target))[0]
    positions[pulled] = centre + dirs[pulled] * target[pulled][:, None]
    normals[pulled] = dirs[pulled]
    print("YXZ2 pulled=%d" % len(pulled))

    # The dome reaches a little below the cut, so that the last of the
    # torn edge is hidden under it rather than left showing.
    overlap = 8.0
    row_count = 30
    base = len(positions)
    dome_pos = []
    dome_nrm = []
    vertex_of = {}
    for column in range(columns):
        middle = (column + 0.5) * az_step - 180.0
        bottom = float(cut[column]) - overlap
        for step in range(row_count):
            here = bottom + (89.0 - bottom) * step / (row_count - 1.0)
            a = math.radians(middle)
            b = math.radians(here)
            u = np.array([math.cos(b) * math.cos(a), math.sin(b), math.cos(b) * math.sin(a)])
            radius_here = float(profile_at([middle], [here])[0]) + lift
            dome_pos.append(centre + u * radius_here)
            dome_nrm.append(u)
            vertex_of[(column, step)] = base + len(dome_pos) - 1
    apex = base + len(dome_pos)
    dome_pos.append(centre + np.array([0.0, 1.0, 0.0]) * (float(profile_at([0.0], [89.5])[0]) + lift))
    dome_nrm.append(np.array([0.0, 1.0, 0.0]))

    dome_index = []
    for column in range(columns):
        nxt = (column + 1) % columns
        for step in range(row_count - 1):
            dome_index.append((vertex_of[(column, step)], vertex_of[(column, step + 1)], vertex_of[(nxt, step + 1)]))
            dome_index.append((vertex_of[(column, step)], vertex_of[(nxt, step + 1)], vertex_of[(nxt, step)]))
        dome_index.append((vertex_of[(column, row_count - 1)], vertex_of[(nxt, row_count - 1)], apex))
    print("YXZ2 domeVertices=%d domeTriangles=%d" % (len(dome_pos), len(dome_index)))

    # The texture.  The new surface has no coordinates of its own, so
    # it is given two: the shell's own coordinates along the seam, so
    # that the join is quiet, and a flat panel of the atlas above it,
    # which is the colour the white of the helmet already is.
    atlas = atlas_of(document, data)
    pale = np.ones(len(positions), dtype=bool)
    if atlas is not None:
        height, width = atlas.shape[:2]
        xi = np.clip((uvs[:, 0] * width).astype(int), 0, width - 1)
        yi = np.clip(((1.0 - uvs[:, 1]) * height).astype(int), 0, height - 1)
        pale = atlas[yi, xi].astype(int).min(axis=1) > 140
    source_mask = shell & pale
    if source_mask.sum() < 100:
        source_mask = shell
    sample = nearest_by_direction(dirs, np.array(dome_pos) - centre, source_mask)
    seam_uv = uvs[sample].copy()
    patch_x, patch_y, patch_size = 2720, 1440, 320
    dome_uv = np.zeros((len(dome_pos), 2))
    for column in range(columns):
        for step in range(row_count):
            here = step / (row_count - 1.0)
            weight = min(1.0, max(0.0, (here - 0.08) / 0.34))
            weight = weight * weight * (3.0 - 2.0 * weight)
            panel_u = (patch_x + patch_size * (column + 0.5) / columns) / 4096.0
            panel_v = (patch_y + patch_size * (1.0 - here)) / 4096.0
            start = seam_uv[vertex_of[(column, step)] - base]
            dome_uv[vertex_of[(column, step)] - base] = start * (1.0 - weight) + np.array([panel_u, panel_v]) * weight
    print("YXZ2 uvReady")

    if report_only:
        print("YXZ2 report only")
        return

    new_triangles = np.concatenate([triangles[~doomed], np.array(dome_index, dtype=np.uint32)])
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
    print("YXZ2 written " + str(output))


if __name__ == "__main__":
    main()
