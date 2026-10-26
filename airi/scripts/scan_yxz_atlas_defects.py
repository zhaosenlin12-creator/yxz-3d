"""Find the marks that still read as damage on the YXZ crown.

The crown close-up shows a magenta band on the star badge, a pink blotch
in the middle of the star, a hard white bar on the visor, a dark blotch
on the visor and a column of white dots on the visor.  Each of those is
painted into the base-colour atlas, so they are found here as pixel
clusters, measured, and written out as crops to look at.

Usage:
  python scripts/scan_yxz_atlas_defects.py <atlas.png> <out-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def clusters(mask, min_area):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), 8)
    found = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        w = int(stats[index, cv2.CC_STAT_WIDTH])
        h = int(stats[index, cv2.CC_STAT_HEIGHT])
        found.append({"area": area, "x": x, "y": y, "w": w, "h": h,
                      "cx": float(centroids[index][0]),
                      "cy": float(centroids[index][1])})
    found.sort(key=lambda item: -item["area"])
    return found


def crop(pixels, box, scale=1):
    x0, y0, x1, y1 = box
    piece = Image.fromarray(pixels[y0:y1, x0:x1])
    if scale != 1:
        piece = piece.resize((piece.width * scale, piece.height * scale),
                             Image.LANCZOS)
    return piece


def main():
    atlas = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    pixels = np.asarray(Image.open(atlas).convert("RGB")).copy()
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    blue = pixels[..., 2].astype(int)

    # Magenta and purple: blue and red both well above green.
    magenta = (blue > 90) & (red > 70) & (blue > green + 45) & (red > green + 15)
    print("YXZ_SCAN magenta_texels=%d" % int(magenta.sum()))
    for item in clusters(magenta, 40)[:14]:
        print("YXZ_SCAN magenta area=%d box=%d,%d %dx%d"
              % (item["area"], item["x"], item["y"], item["w"], item["h"]))
        x0 = max(0, item["x"] - 24)
        y0 = max(0, item["y"] - 24)
        crop(pixels, (x0, y0, x0 + item["w"] + 48, y0 + item["h"] + 48), 3).save(
            out / ("magenta-%d-%d.png" % (item["x"], item["y"])))

    # Pink: red clearly above both green and blue.
    pink = (red > 150) & (red > green + 45) & (red > blue + 25)
    print("YXZ_SCAN pink_texels=%d" % int(pink.sum()))
    for item in clusters(pink, 40)[:14]:
        print("YXZ_SCAN pink area=%d box=%d,%d %dx%d"
              % (item["area"], item["x"], item["y"], item["w"], item["h"]))
        x0 = max(0, item["x"] - 24)
        y0 = max(0, item["y"] - 24)
        crop(pixels, (x0, y0, x0 + item["w"] + 48, y0 + item["h"] + 48), 3).save(
            out / ("pink-%d-%d.png" % (item["x"], item["y"])))

    # The visor: the dark screen of the helmet.
    visor = (red < 120) & (blue > 45) & (blue < 210) & (green < 140)
    print("YXZ_SCAN visor_texels=%d" % int(visor.sum()))

    bright = (red > 150) & (green > 200) & (blue > 220)
    for item in clusters(bright, 6)[:20]:
        ring = cv2.dilate(
            np.zeros_like(bright, dtype=np.uint8), np.ones((1, 1), np.uint8))
        del ring
        print("YXZ_SCAN bright area=%d box=%d,%d %dx%d"
              % (item["area"], item["x"], item["y"], item["w"], item["h"]))

    # Save the known visor window so the marks can be read directly.
    crop(pixels, (1750, 2950, 2450, 3600), 1).save(out / "visor-window.png")
    crop(pixels, (1750, 2950, 2450, 3600), 2).save(out / "visor-window-2x.png")
    print("YXZ_SCAN wrote=%s" % out)


if __name__ == "__main__":
    main()
