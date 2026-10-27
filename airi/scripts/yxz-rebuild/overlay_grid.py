"""Draw a labelled metre grid over a render, so a landmark can be read off.

The render is orthographic, so the mapping from pixels to mesh units is
exact and known; writing it down next to the picture is what turns a
measurement into a number.

  python overlay_grid.py --image front.png --map front.json
"""

from __future__ import annotations

import argparse
import json

from PIL import Image, ImageDraw


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--step", type=float, default=0.1)
    return ap.parse_args()


def main():
    args = parse_args()
    spec = json.loads(open(args.map, encoding="utf-8").read())
    image = Image.open(args.image).convert("RGB")
    draw = ImageDraw.Draw(image)

    width, height = image.size
    scale = spec["pixels_per_unit"]
    ox, oy = spec["origin_px"]
    u = spec["u"]
    v = spec["v"]

    def to_px(a, b):
        """A point a units along u and b units along v, in pixels."""
        return (ox + a * scale, oy - b * scale)

    step = args.step
    limit_u = width / scale
    limit_v = height / scale
    for i in range(int(-limit_u / step), int(limit_u / step) + 1):
        a = i * step
        if abs(a) < 1e-9:
            continue
        x0, y0 = to_px(a, -limit_v)
        x1, y1 = to_px(a, limit_v)
        major = abs(i % 5) == 0
        draw.line([(x0, y0), (x1, y1)], fill=(255, 70, 70) if major else (255, 165, 165))
        if major:
            px, py = to_px(a, -limit_v * 0.98)
            draw.text((px + 2, py + 2), f"{a:+.1f}", fill=(190, 0, 0))
    for i in range(int(-limit_v / step), int(limit_v / step) + 1):
        b = i * step
        if abs(b) < 1e-9:
            continue
        x0, y0 = to_px(-limit_u, b)
        x1, y1 = to_px(limit_u, b)
        major = abs(i % 5) == 0
        draw.line([(x0, y0), (x1, y1)], fill=(70, 140, 255) if major else (165, 205, 255))
        if major:
            px, py = to_px(-limit_u * 0.99, b)
            draw.text((px + 2, py + 2), f"{b:+.1f}", fill=(0, 60, 190))

    out = args.image.replace(".png", "-grid.png")
    image.save(out)
    print("YXZ_GRID_OVERLAY " + out)


main()
