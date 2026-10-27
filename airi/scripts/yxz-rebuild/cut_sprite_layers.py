"""Cut the reference render of YXZ into the layers a living sprite needs.

The reference render is the artwork the character is judged by, so the
cut keeps every pixel of it that is not being animated.  Three things
move on their own: the two eyes, the mouth, and the halo.  They are
lifted out as soft-alpha sprites, and the hole each one leaves is
repaired by inpainting the original pixels around it, so the body that
is left behind is the artwork itself.

Run with the repository's own virtualenv:

    cartoon-print-studio/ai/forge-webui/venv/Scripts/python.exe \\
        airi/scripts/yxz-rebuild/cut_sprite_layers.py
"""

import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SRC = os.path.join(
    REPO, "airi", "packages", "stage-ui", "src", "assets", "yxz", "front-wave.png"
)
OUT = os.path.join(
    REPO, "airi", "packages", "stage-ui", "src", "assets", "yxz", "layers"
)

GLOW_MARGIN = 48
EYE_CORE_MIN = 1200


def save(path, arr):
    Image.fromarray(arr).save(path)
    print("  wrote", os.path.relpath(path, REPO), arr.shape)


def biggest_two(mask):
    from scipy import ndimage as ndi

    lab, n = ndi.label(mask)
    out = []
    for i in range(n):
        yy, xx = np.nonzero(lab == i + 1)
        if len(xx) < EYE_CORE_MIN:
            continue
        out.append(
            {
                "size": int(len(xx)),
                "x0": int(xx.min()),
                "x1": int(xx.max()),
                "y0": int(yy.min()),
                "y1": int(yy.max()),
            }
        )
    out.sort(key=lambda d: -d["size"])
    return out


def lift_sprite(rgb, mask, mode="bright", peak=120.0, gamma=1.8):
    """Lift the pixels under `mask` out as a soft sprite.

    The sprite is the light itself, not a rectangle of the picture with
    its edges cut off.  Each pixel is compared with the surface it sits
    on -- the glass of the visor for an eye, the white of the chin for a
    mouth -- and the alpha is how much of it belongs to the light.  The
    surface underneath is repaired by inpainting the same pixels, so the
    body that is left behind is the picture itself.
    """
    hard = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8))
    bg = cv2.inpaint(rgb, hard, 7, cv2.INPAINT_TELEA)
    delta = rgb.astype(np.float32) - bg.astype(np.float32)
    if mode == "bright":
        delta = np.clip(delta, 0, None)
    else:
        delta = np.clip(-delta, 0, None)
    strength = delta.max(axis=2)
    alpha = np.clip(strength / peak, 0, 1) ** gamma
    alpha[mask > 0] = 1.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
    alpha[mask > 0] = 1.0
    sprite = np.dstack([rgb, (alpha * 255).astype(np.uint8)])
    return sprite, bg


def eye_sprite(rgb, comp, mask_core):
    """The eye as a sprite: its own light and the halo around it.

    The halo is a soft circle of blue around a bright ellipse, and that
    shape is what the sprite is built from -- an ellipse with a falloff
    around it.  Taking the alpha from the difference against the
    inpainted glass instead would carry the inpainting's own edges into
    the sprite, and the eye would come out wearing a rectangle.
    """
    x0, x1 = comp["x0"], comp["x1"]
    y0, y1 = comp["y0"], comp["y1"]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    a = (x1 - x0) / 2.0 * 1.06
    b = (y1 - y0) / 2.0 * 1.06
    H, W = rgb.shape[:2]
    px0 = max(0, int(cx - a * 2.0))
    px1 = min(W, int(cx + a * 2.0))
    py0 = max(0, int(cy - b * 1.85))
    py1 = min(H, int(cy + b * 1.85))
    yy, xx = np.mgrid[py0:py1, px0:px1]
    t = np.sqrt(((xx - cx) / a) ** 2 + ((yy - cy) / b) ** 2)
    core = np.clip((1.0 - t) / 0.09, 0, 1)
    halo = np.clip((1.9 - t) / 0.9, 0, 1) ** 2 * 0.72
    alpha = np.clip(core + halo, 0, 1)
    sub = rgb[py0:py1, px0:px1]
    sprite = np.dstack([sub, (alpha * 255).astype(np.uint8)])
    return sprite, (px0, py0, px1, py1), (cx, cy)


def affine_mouth(sprite, sx, sy, size):
    """Rescale a mouth sprite about its own centre, into a fixed box."""
    h, w = sprite.shape[:2]
    canvas = np.zeros((size[1], size[0], 4), np.uint8)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 0, 1)
    m[0, 0] = sx
    m[1, 1] = sy
    m[0, 2] += size[0] / 2 - w / 2
    m[1, 2] += size[1] / 2 - h / 2
    out = cv2.warpAffine(sprite, m, (size[0], size[1]), flags=cv2.INTER_CUBIC)
    a = out[..., 3:4].astype(np.float32) / 255.0
    out[..., :3] = (out[..., :3] * a + sprite[..., :3].mean(axis=(0, 1)) * (1 - a)).astype(np.uint8)
    return out


def helmet_silhouette(alpha):
    """The top edge of the helmet, measured from the artwork itself.

    The solid body is read column by column and the top of its longest
    run is the helmet's own edge.  Where the halo ring touches the helmet
    the scan lands on the ring instead, so a smooth fit of the rest of the
    edge finds those columns, and they are read across the gap.
    """
    from scipy.interpolate import UnivariateSpline

    H, W = alpha.shape
    solid = alpha > 128
    measured = np.full(W, -1.0)
    for x in range(W):
        ys = np.nonzero(solid[:, x])[0]
        if len(ys) == 0:
            continue
        breaks = np.nonzero(np.diff(ys) > 1)[0]
        starts = np.concatenate(([ys[0]], ys[breaks + 1]))
        ends = np.concatenate((ys[breaks], [ys[-1]]))
        lengths = ends - starts + 1
        long = np.nonzero(lengths >= 150)[0]
        if len(long) == 0:
            continue
        measured[x] = starts[long[np.argmax(lengths[long])]]

    taken = np.nonzero((measured >= 0) & (measured <= 260))[0]
    if len(taken) < 60:
        raise SystemExit("could not measure the helmet edge")
    xs = taken.astype(float)
    ys = measured[taken]

    # A smooth fit of the edge, read again and again with the columns
    # that disagree thrown out.
    keep = np.ones(len(xs), bool)
    for _ in range(10):
        fit = UnivariateSpline(xs[keep], ys[keep], s=len(xs[keep]) * 4.0, k=3)
        fresh = np.abs(ys - fit(xs)) <= 5.0
        if fresh.sum() < 60:
            break
        if (fresh == keep).all():
            break
        keep = fresh
    fit = UnivariateSpline(xs[keep], ys[keep], s=len(xs[keep]) * 4.0, k=3)

    # A column where the scan landed on the ring sits above the smooth
    # edge, and that is how the two are told apart.
    touched = (ys - fit(xs)) < -6.0
    clean_x = xs[~touched]
    clean_y = ys[~touched]

    top = np.full(W, -1.0)
    top[taken[~touched]] = ys[~touched]
    for x in taken[touched]:
        j = np.searchsorted(clean_x, x)
        lo = max(0, j - 7)
        hi = min(len(clean_x), j + 7)
        window_x = clean_x[lo:hi]
        window_y = clean_y[lo:hi]
        if len(window_x) < 4:
            continue
        v = np.vander(window_x - x, 3)
        beta, *_ = np.linalg.lstsq(v, window_y, rcond=None)
        top[x] = beta[-1]
    return top


def main():
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(SRC).convert("RGBA")
    src = np.array(im)
    rgb = src[..., :3].copy()
    alpha = src[..., 3].copy()
    H, W = rgb.shape[:2]
    R, G, B = rgb[..., 0].astype(np.int32), rgb[..., 1].astype(np.int32), rgb[..., 2].astype(np.int32)

    manifest = {"source": os.path.relpath(SRC, REPO), "width": W, "height": H, "layers": {}}

    # ---------------------------------------------------------------- eyes
    eye_core = np.zeros((H, W), np.uint8)
    eye_core[300:640, 400:920] = 1
    cyan = (B > 200) & (G > 190) & (R < 205) & (alpha > 180)
    eye_core &= cyan.astype(np.uint8)
    eye_core = cv2.morphologyEx(eye_core, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    eye_core = cv2.morphologyEx(eye_core, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cands = biggest_two(eye_core)
    if len(cands) < 2:
        raise SystemExit("could not find two eyes: %r" % (cands,))
    print("eyes:", cands[:2])

    eyes = []
    for i, c in enumerate(sorted(cands, key=lambda d: d["x0"])[:2]):
        x0, x1 = c["x0"], c["x1"]
        y0, y1 = c["y0"], c["y1"]
        m = np.zeros((H, W), np.uint8)
        m[y0 : y1 + 1, x0 : x1 + 1] = 1
        hard = cv2.dilate(m, np.ones((9, 9), np.uint8))
        bg = cv2.inpaint(rgb, hard, 9, cv2.INPAINT_TELEA)
        sprite, box, centre = eye_sprite(rgb, c, m)
        rgb = bg
        cx0, cy0, cx1, cy1 = box
        name = "eye_l.png" if i == 0 else "eye_r.png"
        save(os.path.join(OUT, name), sprite)
        eyes.append(
            {
                "file": name,
                "x": cx0,
                "y": cy0,
                "w": int(cx1 - cx0),
                "h": int(cy1 - cy0),
                "cx": centre[0],
                "cy": centre[1],
            }
        )
    manifest["layers"]["eyes"] = eyes

    # --------------------------------------------------------------- mouth
    R, G, B = rgb[..., 0].astype(np.int32), rgb[..., 1].astype(np.int32), rgb[..., 2].astype(np.int32)
    red = (R > 80) & (R > G + 30) & (R > B + 30)
    red[:560, :] = False
    red[700:, :] = False
    red[:, :600] = False
    red[:, 860:] = False
    from scipy import ndimage as ndi

    lab, n = ndi.label(red)
    best = None
    for i in range(n):
        yy, xx = np.nonzero(lab == i + 1)
        if len(xx) < 120:
            continue
        if best is None or len(xx) > best[0]:
            best = (len(xx), xx, yy)
    if best is None:
        raise SystemExit("no mouth found")
    _, mx, my = best
    mx0, mx1 = int(mx.min()), int(mx.max())
    my0, my1 = int(my.min()), int(my.max())
    print("mouth:", mx0, mx1, my0, my1)

    mm = np.zeros((H, W), np.uint8)
    mm[my0 : my1 + 1, mx0 : mx1 + 1] = 1
    mm = cv2.dilate(mm, np.ones((7, 7), np.uint8))
    mouth_sprite, bg = lift_sprite(rgb, mm, 'dark', 90.0, 1.5)
    rgb = bg
    px0 = max(0, mx0 - 26)
    py0 = max(0, my0 - 26)
    px1 = min(W, mx1 + 27)
    py1 = min(H, my1 + 27)
    msub = mouth_sprite[py0:py1, px0:px1]
    box = (msub.shape[1], msub.shape[0])
    variants = {
        "smile": (1.0, 1.0),
        "talk_a": (1.0, 0.74),
        "talk_b": (1.0, 0.46),
        "talk_c": (0.86, 1.02),
        "o": (0.76, 1.16),
        "wide": (1.18, 1.12),
        "small": (0.74, 0.82),
    }
    mouths = []
    for name, (sx, sy) in variants.items():
        fn = "mouth_%s.png" % name
        save(os.path.join(OUT, fn), affine_mouth(msub, sx, sy, box))
        mouths.append({"file": fn, "x": px0, "y": py0, "w": box[0], "h": box[1],
                       "cx": (mx0 + mx1) / 2.0, "cy": (my0 + my1) / 2.0})
    manifest["layers"]["mouths"] = mouths

    # ---------------------------------------------------------------- halo
    # The ring is drawn behind the helmet, so the picture only shows it in
    # the open air above the helmet's own edge.  That edge is measured
    # from the artwork, and the sky above it -- ring, star and glow
    # together -- is the layer that moves on its own.  The body keeps the
    # helmet whole, so the two layers put back together are the picture
    # they came from.
    top = helmet_silhouette(alpha)
    sky = np.zeros((H, W), bool)
    for x in range(W):
        y = top[x]
        if y > 0:
            sky[: int(round(y)), x] = True
    sky &= alpha > 0

    # The ring stays where the artist put it.  It is part of the picture
    # and it goes into the body with everything else, so the head can
    # never come apart -- no seam, no crack, whatever the figure does.
    body = np.dstack([rgb, alpha])
    save(os.path.join(OUT, "body.png"), body)

    # What moves on its own is the light the ring throws, and that is
    # lifted out of the sky as a soft glow: the haze around the ring,
    # without the ring itself.
    soft = np.where(sky & (alpha < 200), alpha, 0).astype(np.float32)
    soft = cv2.GaussianBlur(soft, (0, 0), 7.0)
    soft = np.clip(soft * 2.6, 0, 255).astype(np.uint8)
    rows, cols = np.nonzero(soft)
    gx0, gx1 = int(cols.min()), int(cols.max()) + 1
    gy0, gy1 = int(rows.min()), int(rows.max()) + 1
    glow = np.dstack([rgb[gy0:gy1, gx0:gx1], soft[gy0:gy1, gx0:gx1]])
    save(os.path.join(OUT, "glow.png"), glow)
    manifest["layers"]["glow"] = {"file": "glow.png", "x": gx0, "y": gy0,
                                   "w": gx1 - gx0, "h": gy1 - gy0}

    # ------------------------------------------------------------- preview
    comp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    comp.alpha_composite(Image.fromarray(body))
    for e in eyes:
        im2 = Image.open(os.path.join(OUT, e["file"])).convert("RGBA")
        comp.alpha_composite(im2, (e["x"], e["y"]))
    mimg = Image.open(os.path.join(OUT, "mouth_smile.png")).convert("RGBA")
    comp.alpha_composite(mimg, (mouths[0]["x"], mouths[0]["y"]))
    cd = np.zeros((H, W, 4), np.uint8)
    yy, xx = np.mgrid[0:H, 0:W]
    shade = np.where(((xx // 24) + (yy // 24)) % 2 == 0, 210, 160)
    cd[..., 0] = cd[..., 1] = cd[..., 2] = shade
    cd[..., 3] = 255
    checker = Image.fromarray(cd)
    checker.alpha_composite(comp)
    os.makedirs(os.path.join(REPO, ".run", "verify"), exist_ok=True)
    checker.convert("RGB").save(os.path.join(REPO, ".run", "verify", "layers_preview.png"))

    with io.open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print("manifest written")


if __name__ == "__main__":
    main()
