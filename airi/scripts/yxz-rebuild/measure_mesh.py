"""Measure the reconstructed body, so the rig can be placed on it.

The rig is placed by measurement, and a measurement has to be read off
the mesh itself rather than off a picture of it: the picture is the design
at whatever scale it was drawn, and the mesh is the design at whatever
scale it came out of the reconstruction.  The two do not agree exactly,
and the rig has to fit the mesh.

So the mesh is projected from the front and from the side, and the width
of the silhouette at every height is printed out.  The landmarks are the
turning points of that profile: the crown of the helmet, the widest point
of the head, the neck, the shoulders, the waist, the hips, the crotch,
the knees and the ankles.

  python measure_mesh.py --mesh body.glb [--out .run/measure.json]
"""

from __future__ import annotations

import argparse
import json

import numpy as np


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--resolution", type=int, default=1400)
    return ap.parse_args()


def load(path):
    import trimesh

    scene = trimesh.load(path, force="scene")
    geoms = list(scene.geometry.values())
    mesh = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    points = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    # glTF is Y-up and faces +Z; Blender is Z-up and faces -Y.
    world = np.stack([points[:, 0], -points[:, 2], points[:, 1]], axis=1)
    return world, faces


def rasterise(world, faces, axis, resolution):
    """Rasterise a projection, and report the world box it covers."""
    horizontal = 0 if axis == "front" else 1
    xs = world[:, horizontal]
    zs = world[:, 2]
    lo_x, hi_x = xs.min(), xs.max()
    lo_z, hi_z = zs.min(), zs.max()
    span = max(hi_x - lo_x, hi_z - lo_z)
    scale = (resolution - 2) / span

    grid = np.zeros((resolution, resolution), dtype=bool)
    for face in faces:
        pts = world[face]
        px = ((pts[:, horizontal] - lo_x) * scale + 1).astype(np.int32)
        py = ((hi_z - pts[:, 2]) * scale + 1).astype(np.int32)
        x0, x1 = max(px.min(), 0), min(px.max(), resolution - 1)
        y0, y1 = max(py.min(), 0), min(py.max(), resolution - 1)
        if x1 < x0 or y1 < y0:
            continue
        # A triangle is rasterised by testing every pixel in its box
        # against the three edge functions.
        ax, ay = px[0], py[0]
        bx, by = px[1], py[1]
        cx, cy = px[2], py[2]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if area == 0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        w0 = ((bx - ax) * (ys - ay) - (by - ay) * (xs - ax)) / area
        w1 = ((cx - bx) * (ys - by) - (cy - by) * (xs - bx)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        grid[y0:y1 + 1, x0:x1 + 1] |= inside
    return grid, (lo_x, hi_x, lo_z, hi_z), scale


def profile(grid, box, scale):
    """The silhouette's extent at every height."""
    lo_x, hi_x, lo_z, hi_z = box
    rows = []
    for py in range(grid.shape[0]):
        columns = np.nonzero(grid[py])[0]
        if columns.size == 0:
            continue
        world_low = lo_x + (columns.min() - 1) / scale
        world_high = lo_x + (columns.max() - 1) / scale
        z = hi_z - (py - 1) / scale
        rows.append({
            "z": round(float(z), 4),
            "min": round(float(world_low), 4),
            "max": round(float(world_high), 4),
            "width": round(float(world_high - world_low), 4),
            "count": int(columns.size),
        })
    return rows


def main():
    args = parse_args()
    world, faces = load(args.mesh)
    out = {"bounds": {
        "x": [float(world[:, 0].min()), float(world[:, 0].max())],
        "y": [float(world[:, 1].min()), float(world[:, 1].max())],
        "z": [float(world[:, 2].min()), float(world[:, 2].max())],
    }}
    for axis in ("front", "side"):
        grid, box, scale = rasterise(world, faces, axis, args.resolution)
        rows = profile(grid, box, scale)
        out[axis] = rows
        print(f"YXZ_MEASURE {axis} rows={len(rows)}")
        for row in rows[::4]:
            print("  z={:.4f} min={:.4f} max={:.4f} width={:.4f}".format(
                row["z"], row["min"], row["max"], row["width"]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(out, handle)
        print("YXZ_MEASURE_OUT " + args.out)


main()
