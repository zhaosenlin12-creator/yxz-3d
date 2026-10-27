"""Fit the reference renders onto the reconstructed body.

The character was rebuilt from `front-wave.png`, so the mesh and the front
render are two views of the same thing: one in pixels, one in metres.  The
other two renders -- the back and the character's right side -- are the same
character from other sides, and they are what the mesh cannot show on its
own.

This script measures the three fits.  For each one it finds the scale and
the offset that put the mesh's silhouette on top of the render's silhouette,
which is what turns "a picture of the character" into "pixels of the
character at known positions on the model".  It writes the fit out as JSON
for the rig build and lays the three renders out as one atlas.

    python fit_views.py --mesh .run/shape/body_core.glb --out .run/texture
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[3]
REF_DIR = REPO / "airi" / "packages" / "stage-ui" / "src" / "assets" / "yxz"

# The three renders, in the frame the runtime uses: Y up, the character
# facing +Z, its own left on +X.  `cam` points from the character towards
# the camera, `right` and `up` are the image axes: for a camera looking
# along `f` with up `u`, the image's right is f x u.
#
#   front: the camera is in front of it, so the image's right is the
#          character's left -- the raised waving hand is on the image's
#          right, which is what the render shows.
#   back:  the camera is behind it, so the image's right is the
#          character's right and the waving hand is on the image's left.
#   side:  the camera is on the character's right, so the image's right is
#          the direction it faces.
VIEWS = {
    "front": {"file": "front-wave.png", "cam": (0.0, 0.0, 1.0),
              "right": (1.0, 0.0, 0.0), "up": (0.0, 1.0, 0.0)},
    "back": {"file": "back-wave.png", "cam": (0.0, 0.0, -1.0),
             "right": (-1.0, 0.0, 0.0), "up": (0.0, 1.0, 0.0)},
    "side": {"file": "side-wave.png", "cam": (-1.0, 0.0, 0.0),
             "right": (0.0, 0.0, 1.0), "up": (0.0, 1.0, 0.0)},
}


def load_mesh(path: Path):
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    return vertices, faces


def project(vertices: np.ndarray, right, up) -> np.ndarray:
    """The model's points in an image's own axes, in metres."""
    right = np.asarray(right, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    return np.stack((vertices @ right, vertices @ up), axis=1)


def silhouette(points: np.ndarray, scale: float, tx: float, ty: float,
               width: int, height: int) -> np.ndarray:
    """The model's own silhouette, drawn into a pixel grid."""
    x = np.rint(points[:, 0] * scale + tx).astype(np.int64)
    y = np.rint(ty - points[:, 1] * scale).astype(np.int64)
    inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    mask = np.zeros((height, width), dtype=bool)
    mask[y[inside], x[inside]] = True
    # A splat is a point cloud, so it comes out full of pinholes where the
    # surface is sparse.  Growing it by one cell closes them.
    grown = mask.copy()
    grown[1:, :] |= mask[:-1, :]
    grown[:-1, :] |= mask[1:, :]
    grown[:, 1:] |= mask[:, :-1]
    grown[:, :-1] |= mask[:, 1:]
    return grown


def reference_mask(path: Path, width: int, height: int) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A").resize((width, height), Image.BILINEAR)
    return np.asarray(alpha, dtype=np.float32) / 255.0 > 0.35


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(a, b).sum()) / float(union)


def search(points: np.ndarray, ref: np.ndarray, scales, txs, tys):
    """The best scale and offset, by silhouette overlap."""
    height, width = ref.shape
    best = (0.0, 1.0, 0.0, 0.0)
    for scale in scales:
        for tx in txs:
            for ty in tys:
                score = iou(silhouette(points, scale, tx, ty, width, height), ref)
                if score > best[0]:
                    best = (score, scale, tx, ty)
    return best


def fit_view(points: np.ndarray, image_path: Path):
    """Fit one view, coarse grid first and then a local refinement."""
    width, height = Image.open(image_path).size
    ratio = height / width

    # The coarse pass works on a small grid, because the fit only has to
    # be roughly right before the refinement starts.
    coarse_w = 160
    coarse_h = int(round(coarse_w * ratio))
    ref_coarse = reference_mask(image_path, coarse_w, coarse_h)

    # The reference includes the halo, which the mesh does not have, so the
    # height of the silhouette is a poor measure of the scale: the render
    # is taller than the model by the height of the ring above its head.
    # The area is a better measure, because the ring is a thin band and
    # barely adds to it.
    #
    # The mesh's own area is measured by splatting it, which is what the
    # search scores against, so the two areas are measured the same way.
    span_u = points[:, 0].max() - points[:, 0].min()
    span_v = points[:, 1].max() - points[:, 1].min()
    bbox_scale = 0.85 * min(coarse_w / max(span_u, 1e-6),
                             coarse_h / max(span_v, 1e-6))
    probe = silhouette(points, bbox_scale,
                       coarse_w * 0.5 - points[:, 0].mean() * bbox_scale,
                       coarse_h * 0.5 + points[:, 1].mean() * bbox_scale,
                       coarse_w, coarse_h)
    ref_area = float(ref_coarse.sum())
    mesh_area = float(probe.sum())
    scale0 = bbox_scale * float(np.sqrt(ref_area / max(mesh_area, 1.0)))

    best = (0.0, scale0, 0.0, 0.0)
    for factor in np.linspace(0.86, 1.16, 16):
        scale = scale0 * factor
        # The character stands on the floor in both the render and the
        # model, so their feet are the one landmark the two agree on; the
        # ring above the head is not.
        cx = points[:, 0].mean()
        cy = points[:, 1].min()
        tx = coarse_w * 0.5 - cx * scale
        ty = coarse_h - 4.0 - cy * scale
        txs = tx + np.linspace(-14, 14, 11)
        tys = ty + np.linspace(-14, 14, 11)
        score, s, bx, by = search(points, ref_coarse, [scale], txs, tys)
        if score > best[0]:
            best = (score, s, bx, by)

    _, scale, tx, ty = best

    if best[0] <= 0.0:
        raise SystemExit("YXZ_FIT_FAILED " + str(image_path))

    # The refinement pass works on a bigger grid and searches a smaller
    # neighbourhood, which is what puts the silhouette on the render
    # rather than merely near it.
    fine_w = 480
    fine_h = int(round(fine_w * ratio))
    ref_fine = reference_mask(image_path, fine_w, fine_h)
    scale = scale * fine_w / coarse_w
    tx = tx * fine_w / coarse_w
    ty = ty * fine_w / coarse_w
    scales = np.linspace(scale * 0.985, scale * 1.015, 13)
    txs = np.linspace(tx - 12, tx + 12, 17)
    tys = np.linspace(ty - 12, ty + 12, 17)
    score, scale, tx, ty = search(points, ref_fine, scales, txs, tys)

    return {"scale": float(scale), "tx": float(tx), "ty": float(ty),
            "iou": float(score), "width": fine_w, "height": fine_h}


def overlay(image_path: Path, points: np.ndarray, fit: dict) -> Image.Image:
    """The render with the model's silhouette drawn over it."""
    image = Image.open(image_path).convert("RGBA")
    width, height = image.size
    factor = width / float(fit["width"])
    mask = silhouette(points, fit["scale"] * factor,
                      fit["tx"] * factor, fit["ty"] * factor, width, height)
    out = image.copy()
    pixels = np.asarray(out).copy().astype(np.float32)
    edge = mask & ~(np.roll(mask, 1, axis=0) & np.roll(mask, -1, axis=0)
                    & np.roll(mask, 1, axis=1) & np.roll(mask, -1, axis=1))
    pixels[edge, 0] = 255
    pixels[edge, 1] = 0
    pixels[edge, 2] = 0
    pixels[edge, 3] = 255
    return Image.fromarray(pixels.astype(np.uint8))


def unlight(image: Image.Image, strength: float = 0.35) -> Image.Image:
    """Take the soft shading out of a render, leaving the paint.

    The renders are lit, and the model is going to be lit again by the
    stage: baking the render's own shadows in would double them.  What is
    wanted is the paint, so the image is divided by a heavily blurred
    version of itself -- the shading is the blur, and the paint is what
    is left over.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    blur = np.asarray(
        Image.fromarray((luminance * 255.0).astype(np.uint8))
        .filter(ImageFilter.GaussianBlur(radius=26)),
        dtype=np.float32) / 255.0
    level = float(np.mean(luminance[blur > 0.02])) if (blur > 0.02).any() else 0.5
    gain = np.clip(level / np.maximum(blur, 0.02), 0.55, 1.8)
    corrected = np.clip(rgb * gain[:, :, None], 0.0, 1.0)
    mixed = rgb * (1.0 - strength) + corrected * strength
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.float32) / 255.0
    out = np.concatenate([mixed, alpha[:, :, None]], axis=2)
    return Image.fromarray((out * 255.0).astype(np.uint8))


def fill_holes(image: Image.Image) -> Image.Image:
    """Fill the transparent ground around the character with its own edge.

    The renders have the character on an empty background, and the model's
    surface does not stop exactly where the render's does: the mesh is a
    reconstruction and it overhangs the render's outline by a few pixels
    here and there.  A surface that samples past the outline would take
    the background with it -- a black rim around the whole character --
    so the ground is filled with the colour of the nearest edge pixel.
    """
    from scipy import ndimage

    pixels = np.asarray(image.convert("RGBA"), dtype=np.float32)
    rgb = pixels[:, :, :3]
    alpha = pixels[:, :, 3]
    known = alpha > 0.5
    if not known.any():
        return image
    _, indices = ndimage.distance_transform_edt(~known, return_indices=True)
    filled = rgb[indices[0], indices[1]]
    out = np.concatenate(
        [filled, np.full(alpha.shape + (1,), 255.0, dtype=np.float32)], axis=2)
    out[known, :3] = rgb[known]
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--unlight", type=float, default=0.35)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    vertices, _ = load_mesh(Path(args.mesh))
    print("YXZ_FIT verts", len(vertices))

    fits = {}
    cells = {}
    for name, view in VIEWS.items():
        image_path = REF_DIR / view["file"]
        points = project(vertices, view["right"], view["up"])
        fit = fit_view(points, image_path)
        fits[name] = {**fit, **view}
        print(f"YXZ_FIT {name} scale={fit['scale']:.4f} tx={fit['tx']:.2f} "
              f"ty={fit['ty']:.2f} iou={fit['iou']:.3f}")
        overlay(image_path, points, fit).save(out / f"overlay_{name}.png")
        cells[name] = fill_holes(
            unlight(Image.open(image_path).convert("RGBA"), args.unlight))

    # The atlas: the three renders laid out in a grid, one cell each, with
    # the fourth cell left empty.  Every face of the model is projected
    # into the cell of the view it is seen best in, so the atlas is the
    # renders themselves and the model's paint lands in them exactly.
    cell_w = max(cell.width for cell in cells.values())
    cell_h = max(cell.height for cell in cells.values())
    slots = {"front": (0, 0), "back": (1, 0), "side": (0, 1)}
    atlas = Image.new("RGBA", (cell_w * 2, cell_h * 2), (0, 0, 0, 0))
    for name, (column, row) in slots.items():
        atlas.paste(cells[name], (column * cell_w, row * cell_h))
    atlas.save(out / "atlas.png")
    print("YXZ_ATLAS", out / "atlas.png", atlas.size)

    (out / "bake.json").write_text(json.dumps({
        "views": fits,
        "atlas": {"width": atlas.width, "height": atlas.height,
                  "cell_width": cell_w, "cell_height": cell_h,
                  "slots": {name: {"column": slot[0], "row": slot[1]}
                            for name, slot in slots.items()}},
    }, indent=2), encoding="utf-8")
    print("YXZ_BAKE_JSON", out / "bake.json")


if __name__ == "__main__":
    main()
