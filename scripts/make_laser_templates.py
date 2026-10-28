# -*- coding: utf-8 -*-
"""Generate the laser-cut card back template (宜昌 / 科技 主视觉).

The card back is the fixed face of the activity card, so it has to survive
being printed on wood / acrylic: a night skyline of the Yichang landmarks
(三峡大坝, 夷陵长江大桥, 黄陵庙, 葛洲坝) with a tech layer (circuit traces,
data grid, HUD arcs, particles) and a warm horizon glow.

The middle band is deliberately kept calm -- the activity title is typeset on
top of it at render time by ``backend/laser_card.py``, so the title always
matches the event instead of being baked into the artwork.

Run:  python scripts/make_laser_templates.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 2400, 1350
OUT_DIR = Path(__file__).resolve().parent.parent / "cartoon-print-studio" / "backend" / "assets" / "laser"
OUT_NAME = "activity_yichang.png"

RNG = random.Random(20261028)


# --- helpers -------------------------------------------------------------

def vgradient(stops, height=None, width=None):
    """Vertical gradient from ``[(pos 0..1, (r,g,b)), ...]``."""
    height = height or H
    width = width or W
    ys = np.linspace(0.0, 1.0, height)
    colors = np.zeros((height, 3), dtype=np.float64)
    stops = sorted(stops, key=lambda s: s[0])
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        mask = (ys >= p0) & (ys <= p1)
        if not mask.any():
            continue
        t = ((ys[mask] - p0) / max(1e-6, p1 - p0))[:, None]
        colors[mask] = np.array(c0)[None, :] * (1 - t) + np.array(c1)[None, :] * t
    colors[ys < stops[0][0]] = stops[0][1]
    colors[ys > stops[-1][0]] = stops[-1][1]
    arr = np.repeat(colors[:, None, :], width, axis=1)
    return Image.fromarray(arr.astype(np.uint8))


def add_glow(image, center, radius, color, strength=1.0):
    """Additive radial glow."""
    cx, cy = center
    arr = np.asarray(image, dtype=np.float64)
    yy, xx = np.mgrid[0:image.height, 0:image.width]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(1.0, radius)
    falloff = np.clip(1.0 - d, 0.0, 1.0) ** 2.2
    for i in range(3):
        arr[:, :, i] += color[i] * falloff * strength
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# --- sky ----------------------------------------------------------------

def build_sky():
    sky = vgradient([
        (0.00, (3, 9, 20)),
        (0.26, (7, 26, 52)),
        (0.50, (12, 52, 88)),
        (0.66, (20, 84, 116)),
        (0.78, (52, 124, 138)),
        (0.84, (128, 150, 138)),
        (0.87, (196, 158, 118)),
    ])
    sky = add_glow(sky, (0.70 * W, 0.855 * H), 0.50 * W, (255, 150, 62), 1.15)
    sky = add_glow(sky, (0.26 * W, 0.845 * H), 0.30 * W, (255, 132, 66), 0.55)
    sky = add_glow(sky, (0.18 * W, 0.22 * H), 0.40 * W, (36, 120, 190), 0.35)
    sky = add_glow(sky, (0.50 * W, 0.40 * H), 0.42 * W, (24, 96, 150), 0.30)
    return sky


def draw_stars(image):
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(420):
        x = RNG.uniform(0, W)
        y = RNG.uniform(0, 0.62 * H)
        if RNG.random() > (1.0 - y / (0.62 * H)) * 0.9 + 0.1:
            continue
        r = RNG.choice([1, 1, 1, 2, 2, 3])
        alpha = RNG.randint(70, 225)
        tint = RNG.choice([(255, 255, 255), (206, 236, 255), (255, 236, 196)])
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*tint, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), layer)

    halo = Image.new("RGBA", image.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for _ in range(9):
        x = RNG.uniform(0.04 * W, 0.96 * W)
        y = RNG.uniform(0.05 * H, 0.45 * H)
        r = RNG.uniform(4, 7)
        hd.ellipse((x - r, y - r, x + r, y + r), fill=(220, 244, 255, 190))
    halo = halo.filter(ImageFilter.GaussianBlur(9))
    image = Image.alpha_composite(image, halo)
    return image.convert("RGB")


def draw_far_ridge(image):
    """Distant hills behind the skyline."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ranges = (
        (-40.0, 0.52 * W, (12, 40, 62), 120),
        (0.60 * W, W + 40.0, (16, 44, 62), 96),
    )
    for offset in (0.0, 0.045):
        for x_start, x_end, base, a in ranges:
            points = [(x_start, H)]
            x = x_start
            y = 0.74 * H - offset * H
            while x < x_end:
                step = RNG.uniform(90, 260)
                y += RNG.uniform(-38, 26)
                y = max(0.66 * H - offset * H, min(0.80 * H, y))
                points.append((x, y))
                x += step
            points.append((x_end, min(0.80 * H, y)))
            draw.polygon(points, fill=(*base, a if offset == 0 else a + 40))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


# --- tech layer ---------------------------------------------------------

def draw_circuit_traces(image):
    """Circuit traces + nodes, kept out of the centre title band."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cyan = (126, 226, 255)

    def trace(x, y, steps, weight):
        points = [(x, y)]
        for _ in range(steps):
            mode = RNG.random()
            if mode < 0.4:
                x += RNG.choice([-1, 1]) * RNG.uniform(60, 190)
            elif mode < 0.75:
                y += RNG.choice([-1, 1]) * RNG.uniform(45, 120)
            else:
                d = RNG.choice([-1, 1]) * RNG.uniform(50, 130)
                x += d
                y += d * 0.6
            x = max(-50, min(W + 50, x))
            y = max(-50, min(0.80 * H, y))
            points.append((x, y))
        draw.line(points, fill=(*cyan, 58), width=weight, joint="curve")
        for px, py in (points[0], points[-1]):
            r = weight * 2.6
            draw.ellipse((px - r, py - r, px + r, py + r), outline=(*cyan, 120), width=max(1, weight // 2))
            draw.ellipse((px - r * 0.35, py - r * 0.35, px + r * 0.35, py + r * 0.35), fill=(*cyan, 190))

    for _ in range(9):
        trace(RNG.uniform(-30, 0.30 * W), RNG.uniform(0.02 * H, 0.62 * H), RNG.randint(3, 6), 2)
    for _ in range(9):
        trace(RNG.uniform(0.72 * W, W + 30), RNG.uniform(0.02 * H, 0.62 * H), RNG.randint(3, 6), 2)
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def draw_data_grid(image):
    """Faint measurement grid in the upper corners."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    step = 60
    for x in range(0, int(0.30 * W), step):
        draw.line([(x, 0), (x, 0.70 * H)], fill=(120, 200, 235, 16), width=1)
    for x in range(int(0.74 * W), W, step):
        draw.line([(x, 0), (x, 0.70 * H)], fill=(120, 200, 235, 16), width=1)
    for y in range(0, int(0.70 * H), step):
        draw.line([(0, y), (int(0.28 * W), y)], fill=(120, 200, 235, 14), width=1)
        draw.line([(int(0.76 * W), y), (W, y)], fill=(120, 200, 235, 14), width=1)
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def draw_hud(image):
    """Concentric HUD arcs + a rotating sweep."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cyan = (140, 232, 255)

    def arcs(cx, cy, radii, alpha):
        for radius in radii:
            start = RNG.uniform(0, 360)
            sweep = RNG.uniform(60, 200)
            draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
                     start, start + sweep, fill=(*cyan, alpha), width=2)

    arcs(int(0.10 * W), int(0.20 * H), [70, 108, 150, 196], 62)
    arcs(int(0.92 * W), int(0.16 * H), [90, 132, 178], 55)
    arcs(int(0.50 * W), int(0.40 * H), [300, 352], 22)

    cx, cy = int(0.10 * W), int(0.20 * H)
    for i, alpha in ((0, 70), (1, 34)):
        angle = math.radians(-58 + 12 * i)
        draw.line([(cx, cy), (cx + 196 * math.cos(angle), cy + 196 * math.sin(angle))],
                  fill=(*cyan, alpha), width=2)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=(*cyan, 150))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def draw_particles(image):
    """Rising data particles with a faint vertical trail."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(150):
        x = RNG.uniform(0, W)
        y = RNG.uniform(0.10 * H, 0.80 * H)
        length = RNG.uniform(14, 70)
        alpha = RNG.randint(30, 120)
        tint = RNG.choice([(168, 236, 255), (255, 214, 150), (255, 255, 255)])
        draw.line([(x, y), (x, y - length)], fill=(*tint, alpha), width=RNG.choice([1, 1, 2]))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


# --- Yichang skyline ----------------------------------------------------

INK = (4, 10, 18)
RIM = (120, 214, 245)


def _rim(draw, points, alpha=90, width=2):
    draw.line(points, fill=(*RIM, alpha), width=width, joint="curve")


def draw_temple(draw, cx, base_y, width, height):
    """黄陵庙 -- a traditional tiered roof silhouette."""
    x0 = cx - width / 2
    x1 = cx + width / 2
    draw.rectangle((x0 - width * 0.12, base_y - height * 0.10, x1 + width * 0.12, base_y), fill=INK)
    body_bottom = base_y - height * 0.10
    lower_top = body_bottom - height * 0.42
    draw.rectangle((x0 + width * 0.10, lower_top, x1 - width * 0.10, body_bottom), fill=INK)
    draw.polygon([
        (x0 - width * 0.10, lower_top),
        (x0 + width * 0.24, lower_top - height * 0.20),
        (x0 + width * 0.32, lower_top - height * 0.24),
        (x1 - width * 0.32, lower_top - height * 0.24),
        (x1 - width * 0.24, lower_top - height * 0.20),
        (x1 + width * 0.10, lower_top),
    ], fill=INK)
    upper_bottom = lower_top - height * 0.22
    upper_top = upper_bottom - height * 0.34
    draw.rectangle((x0 + width * 0.24, upper_top, x1 - width * 0.24, upper_bottom), fill=INK)
    draw.polygon([
        (x0 + width * 0.10, upper_bottom),
        (x0 + width * 0.34, upper_bottom - height * 0.17),
        (x0 + width * 0.50, upper_top - height * 0.06),
        (x1 - width * 0.50, upper_top - height * 0.06),
        (x1 - width * 0.34, upper_bottom - height * 0.17),
        (x1 - width * 0.10, upper_bottom),
    ], fill=INK)
    _rim(draw, [
        (x0 + width * 0.10, upper_bottom),
        (x0 + width * 0.34, upper_bottom - height * 0.17),
        (x0 + width * 0.50, upper_top - height * 0.06),
        (x1 - width * 0.50, upper_top - height * 0.06),
        (x1 - width * 0.34, upper_bottom - height * 0.17),
        (x1 - width * 0.10, upper_bottom),
    ], 120, 2)


def draw_bridge(draw, deck_y, x_left, x_right, pylon_xs, height):
    """夷陵长江大桥 -- cable-stayed bridge with inverted-Y pylons."""
    draw.rectangle((x_left, deck_y, x_right, deck_y + height * 0.035), fill=INK)
    step = 34
    for x in range(int(x_left), int(x_right), step):
        draw.line([(x, deck_y), (x + step // 2, deck_y + height * 0.035)], fill=(*RIM, 46), width=1)
    mid = (x_left + x_right) / 2
    for px in pylon_xs:
        top = deck_y - height
        half = height * 0.055
        draw.polygon([
            (px - half * 1.7, deck_y),
            (px - half * 0.45, top + height * 0.26),
            (px + half * 0.45, top + height * 0.26),
            (px + half * 1.7, deck_y),
        ], fill=INK)
        draw.polygon([
            (px - half * 0.40, top + height * 0.28),
            (px - half * 0.22, top),
            (px + half * 0.22, top),
            (px + half * 0.40, top + height * 0.28),
        ], fill=INK)
        for i in range(9):
            frac = (i + 1) / 9.0
            if px < mid:
                far = px + (x_right - px) * frac * 0.92
                near = px - (px - x_left) * frac * 0.92
            else:
                far = px - (px - x_left) * frac * 0.92
                near = px + (x_right - px) * frac * 0.92
            cable_top = top + height * 0.06 + abs(frac - 0.45) * height * 0.30
            draw.line([(px, cable_top), (far, deck_y)], fill=(*RIM, 70), width=1)
            draw.line([(px, cable_top), (near, deck_y)], fill=(*RIM, 55), width=1)
        _rim(draw, [(px - half * 0.22, top), (px + half * 0.22, top)], 150, 2)


def draw_dam(draw, x0, x1, crest_y, base_y, gates, rim_alpha=110):
    """三峡大坝 -- a curved gravity dam with spillway gates."""
    arch = (base_y - crest_y) * 0.30
    draw.polygon([
        (x0, crest_y + arch * 0.55),
        ((x0 + x1) / 2, crest_y),
        (x1, crest_y + arch * 0.55),
        (x1, base_y),
        (x0, base_y),
    ], fill=INK)
    draw.line([(x0, crest_y + arch * 0.55), ((x0 + x1) / 2, crest_y), (x1, crest_y + arch * 0.55)],
              fill=(*RIM, rim_alpha), width=3)
    # dam body divisions + a warm lit powerhouse block
    for i in range(1, 6):
        t = i / 6.0
        cx = x0 + (x1 - x0) * t
        top = crest_y + arch * 0.55 * (1 - abs(t - 0.5) * 2)
        draw.line([(cx, top), (cx, base_y)], fill=(*RIM, 34), width=1)
    draw.rectangle((x0 + (x1 - x0) * 0.04, base_y - (base_y - crest_y) * 0.30,
                    x0 + (x1 - x0) * 0.20, base_y), fill=(8, 18, 30))
    draw.rectangle((x0 + (x1 - x0) * 0.05, base_y - (base_y - crest_y) * 0.26,
                    x0 + (x1 - x0) * 0.19, base_y - (base_y - crest_y) * 0.20),
                   fill=(255, 186, 104, 150))
    span = (x1 - x0) * 0.78
    gx0 = x0 + (x1 - x0) * 0.11
    gate_w = span / gates
    gh = (base_y - crest_y) * 0.62
    for i in range(gates):
        gx = gx0 + i * gate_w
        draw.rounded_rectangle((gx + gate_w * 0.10, base_y - gh, gx + gate_w * 0.90, base_y),
                               radius=int(gate_w * 0.30), fill=(6, 16, 28))
        draw.arc((gx + gate_w * 0.10, base_y - gh, gx + gate_w * 0.90, base_y),
                 180, 360, fill=(*RIM, 46), width=1)


def draw_skyline():
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    deck_y = 0.815 * H

    for _ in range(16):
        x = RNG.uniform(0.44 * W, 0.52 * W)
        w = RNG.uniform(24, 54)
        h = RNG.uniform(40, 120)
        draw.rectangle((x, deck_y - h, x + w, deck_y), fill=INK)
        for _ in range(RNG.randint(3, 8)):
            wx = RNG.uniform(x + 4, x + w - 8)
            wy = RNG.uniform(deck_y - h + 8, deck_y - 10)
            draw.rectangle((wx, wy, wx + 4, wy + 5),
                           fill=RNG.choice([(255, 196, 120, 190), (150, 220, 250, 150)]))

    draw_temple(draw, int(0.085 * W), int(0.815 * H), 150, 150)
    draw_bridge(draw, deck_y, int(0.13 * W), int(0.47 * W), [int(0.20 * W), int(0.335 * W)], 0.40 * H)
    draw_dam(draw, int(0.52 * W), int(0.88 * W), 0.665 * H, 0.875 * H, 7)
    draw_dam(draw, int(0.895 * W), int(0.995 * W), 0.760 * H, 0.875 * H, 3, rim_alpha=80)

    return layer


# --- river --------------------------------------------------------------

def draw_river(image):
    horizon = int(0.868 * H)
    river = vgradient([
        (0.00, (58, 116, 128)),
        (0.10, (16, 62, 88)),
        (0.45, (8, 34, 56)),
        (1.00, (3, 12, 22)),
    ], height=H - horizon)
    river = river.resize((W, H - horizon))

    arr = np.asarray(river, dtype=np.float64)
    xx = np.arange(W)[None, :]
    band = np.exp(-((xx - 0.70 * W) ** 2) / (2 * (0.075 * W) ** 2))
    for i, c in enumerate((255, 170, 92)):
        arr[:, :, i] += c * band * np.linspace(0.55, 0.0, arr.shape[0])[:, None]
    for cx, width in ((0.20 * W, 0.05 * W), (0.33 * W, 0.04 * W), (0.70 * W, 0.20 * W)):
        band = np.exp(-((xx - cx) ** 2) / (2 * width ** 2))
        for i, c in enumerate((90, 200, 240)):
            arr[:, :, i] += c * band * np.linspace(0.28, 0.0, arr.shape[0])[:, None]
    river = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    layer = Image.new("RGBA", (W, H - horizon), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(260):
        y = RNG.uniform(0, H - horizon)
        x = RNG.uniform(-40, W)
        length = RNG.uniform(30, 210)
        alpha = int(46 * (1 - y / (H - horizon)) ** 1.4) + 6
        tint = RNG.choice([(180, 226, 246), (255, 214, 158), (150, 200, 230)])
        draw.line([(x, y), (x + length, y)], fill=(*tint, alpha), width=RNG.choice([1, 1, 2]))
    river = Image.alpha_composite(river.convert("RGBA"), layer).convert("RGB")

    out = image.copy()
    out.paste(river, (0, horizon))
    seam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(seam).rectangle((0, horizon - 20, W, horizon + 20), fill=(90, 160, 170, 70))
    seam = seam.filter(ImageFilter.GaussianBlur(14))
    out = Image.alpha_composite(out.convert("RGBA"), seam).convert("RGB")
    return out


def finish(image):
    """Vignette, title-zone glow, grain."""
    arr = np.asarray(image, dtype=np.float64)
    yy, xx = np.mgrid[0:H, 0:W]
    dx = (xx - W / 2) / (W / 2)
    dy = (yy - H / 2) / (H / 2)
    dist = np.sqrt(dx * dx + dy * dy)
    vign = 1.0 - 0.34 * np.clip(dist - 0.35, 0, None) ** 1.6
    arr *= vign[:, :, None]
    lum = arr.mean(axis=2, keepdims=True) / 255.0
    arr[:, :, 2] += 12 * (1 - lum)[:, :, 0]
    grain = np.random.default_rng(7).normal(0, 2.1, (H, W, 1))
    arr += grain
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr, "RGB")
    out = add_glow(out, (0.50 * W, 0.40 * H), 0.44 * W, (18, 74, 120), 0.55)
    return out


def main():
    image = build_sky()
    image = draw_stars(image)
    image = draw_data_grid(image)
    image = draw_hud(image)
    image = draw_circuit_traces(image)
    image = draw_particles(image)
    image = draw_far_ridge(image)

    skyline = draw_skyline()
    image = Image.alpha_composite(image.convert("RGBA"), skyline).convert("RGB")

    image = draw_river(image)
    image = finish(image)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / OUT_NAME
    image.save(target, "PNG", optimize=True)
    print(f"wrote {target} ({target.stat().st_size} bytes, {image.size[0]}x{image.size[1]})")


if __name__ == "__main__":
    main()
