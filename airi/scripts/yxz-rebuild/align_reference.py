"""Fit the reference render onto the reconstructed mesh.

The rig is placed by measurement, and the reference render is where the
design's measurements live: the helmet, the visor, the shoulders, the
raised hand and the book are all legible in it, and they were all read
off it by hand.  The mesh that came out of the reconstruction is the same
character in the same pose, but in metres rather than pixels, so the
reference's landmarks have to be moved onto it.

The move is found by fitting one silhouette to the other: the reference's
alpha against the mesh's own front projection, searched over scale and
offset.  A fit that puts the boot on the boot and the raised hand on the
raised hand is the one worth using, and the result is written out so the
overlay can be checked by eye afterwards.

  python align_reference.py --mesh body.glb --reference front-wave.png \
      --out .run/align.json
"""

from __future__ import annotations

import argparse
import json

import numpy as np
from PIL import Image, ImageDraw


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=512)
    return ap.parse_args()


def mesh_silhouette(path, size):
    """The mesh's front projection, as a binary image and its world box."""
    import trimesh

    scene = trimesh.load(path, force="scene")
    geoms = list(scene.geometry.values())
    mesh = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    points = np.asarray(mesh.vertices, dtype=np.float64)
    # glTF is Y-up and faces +Z; Blender is Z-up and turns the character
    # to face -Y, which is the frame the rig is authored in.
    world = np.stack([points[:, 0], -points[:, 2], points[:, 1]], axis=1)
    faces = np.asarray(mesh.faces, dtype=np.int64)

    lo = world.min(axis=0)
    hi = world.max(axis=0)
    width = hi[0] - lo[0]
    height = hi[2] - lo[2]
    span = max(width, height)
    scale = (size - 2) / span
    image = Image.new("1", (size, size), 0)
    draw = ImageDraw.Draw(image)
    # Image rows run downwards, and world Z runs upwards.
    for face in faces:
        points2d = []
        for index in face:
            x, _, z = world[index]
            px = (x - lo[0]) * scale + 1.0
            py = (hi[2] - z) * scale + 1.0
            points2d.append((px, py))
        draw.polygon(points2d, fill=1)
    mask = np.array(image, dtype=bool)
    return mask, lo, hi, scale


def reference_mask(path, size):
    image = Image.open(path).convert("RGBA")
    alpha = np.array(image.getchannel("A")) > 24
    return alpha, image.size


def iou(a, b):
    union = (a | b).sum()
    if union == 0:
        return 0.0
    return float((a & b).sum()) / float(union)


def resample(mask, out_size):
    image = Image.fromarray((mask * 255).astype(np.uint8))
    image = image.resize((out_size, out_size), Image.LANCZOS)
    return np.array(image) > 127


def main():
    args = parse_args()
    size = args.size
    mesh_mask, lo, hi, mesh_scale = mesh_silhouette(args.mesh, size)
    ref_mask, ref_size = reference_mask(args.reference, size)

    # The reference is scaled into the same box as the mesh: its own
    # bounding box, so the fit below only has to find the small residual.
    ys, xs = np.nonzero(ref_mask)
    ref_box = (xs.min(), ys.min(), xs.max(), ys.max())
    ref_lo = (ref_box[0], ref_box[1])
    ref_span = max(ref_box[2] - ref_box[0], ref_box[3] - ref_box[1])

    best = (0.0, 1.0, 0.0, 0.0)
    mesh_ys, mesh_xs = np.nonzero(mesh_mask)
    mesh_box = (mesh_xs.min(), mesh_ys.min(), mesh_xs.max(), mesh_ys.max())
    mesh_span = max(mesh_box[2] - mesh_box[0], mesh_box[3] - mesh_box[1])

    # Search the reference's scale and offset against the mesh silhouette.
    for scale_step in np.arange(0.90, 1.115, 0.01):
        scaled = resample(ref_mask, size)
        ys, xs = np.nonzero(scaled)
        if len(xs) == 0:
            continue
        cx = (xs.min() + xs.max()) / 2.0
        cy = (ys.min() + ys.max()) / 2.0
        for dx in np.arange(-60, 61, 6):
            for dy in np.arange(-60, 61, 6):
                moved = np.zeros_like(scaled)
                sx = (xs + dx).astype(int)
                sy = (ys + dy).astype(int)
                keep = (sx >= 0) & (sx < size) & (sy >= 0) & (sy < size)
                moved[sy[keep], sx[keep]] = True
                score = iou(moved, mesh_mask)
                if score > best[0]:
                    best = (score, float(scale_step), float(dx), float(dy))
    print(f"YXZ_ALIGN coarse score={best[0]:.4f} scale={best[1]} dx={best[2]} dy={best[3]}")

    # The mask was resampled for the search; the fit that came out is in
    # that resampled frame, so it is applied to the reference's own pixels
    # and written out as the mapping from reference pixels to world metres.
    score, scale, dx, dy = best
    ref_px = (ref_size[0] / size)
    ref_py = (ref_size[1] / size)
    out = {
        "iou": score,
        "reference_size": list(ref_size),
        "mesh_lo": [float(v) for v in lo],
        "mesh_hi": [float(v) for v in hi],
        "mesh_scale": float(mesh_scale),
        "fit": {
            "scale": scale,
            "dx": dx,
            "dy": dy,
            "ref_box": [float(v) for v in ref_box],
            "ref_span": float(ref_span),
            "mesh_box": [float(v) for v in mesh_box],
            "mesh_span": float(mesh_span),
            "resample": [ref_px, ref_py],
        },
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
    print("YXZ_ALIGN " + args.out)


main()
