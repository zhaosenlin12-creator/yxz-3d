"""Find the marks on a close-up capture and write their pixels out.

The capture is the model's own render, so the marks are found by their
colour rather than by their place: the violet smear on the star badge,
the pale bar and the pale flecks on the dark screen of the visor.  The
pixels are written as a list of points, which the texel probe then
turns into atlas coordinates.

Usage:
  python scripts/find_yxz_render_defects.py <capture.png> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def cluster(points, gap=6):
    """Group points that sit close together."""
    if not len(points):
        return []
    mask = np.zeros((1024, 1024), dtype=np.uint8)
    array = np.asarray(points, dtype=int)
    mask[array[:, 1], array[:, 0]] = 1
    size = 2 * gap + 1
    joined = cv2.dilate(mask, np.ones((size, size), np.uint8))
    count, labels = cv2.connectedComponents(joined, 8)
    groups = []
    for index in range(1, count):
        selection = (labels == index) & (mask > 0)
        ys, xs = np.nonzero(selection)
        if len(xs):
            groups.append(list(zip(xs.tolist(), ys.tolist())))
    return groups


def main():
    capture = Image.open(sys.argv[1]).convert("RGB")
    pixels = np.asarray(capture).astype(int)
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    height, width = red.shape
    y_min = 0
    y_max = height - 1
    x_max = width - 1
    max_per_group = 0
    if "--y-min" in sys.argv:
        y_min = int(sys.argv[sys.argv.index("--y-min") + 1])
    if "--y-max" in sys.argv:
        y_max = int(sys.argv[sys.argv.index("--y-max") + 1])
    if "--x-max" in sys.argv:
        x_max = int(sys.argv[sys.argv.index("--x-max") + 1])
    if "--max-per-group" in sys.argv:
        max_per_group = int(sys.argv[sys.argv.index("--max-per-group") + 1])

    def groups_of(mask, min_area=4, max_area=4000):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), 8)
        found = []
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < min_area or area > max_area:
                continue
            ys, xs = np.nonzero(labels == index)
            if ys.min() < y_min or ys.max() > y_max:
                continue
            if xs.max() > x_max:
                continue
            found.append((area, int(xs.min()), int(ys.min()),
                          int(xs.max()), int(ys.max()), list(zip(xs.tolist(), ys.tolist()))))
        return found

    # The violet smear on the star badge: blue and red both well above
    # green, which nothing else in the head is.
    violet = (blue > 90) & (red > 60) & (blue > green + 35) & (red > green + 5)
    categories = {"star": groups_of(violet, 4, 6000)}

    # Marks on the dark screen of the visor: much lighter than the
    # screen, or much darker.  The eyes are bright too, and they are
    # shapes rather than marks, so they are left out by their size.
    pale = (red > 130) & (green > 145) & (blue > 155)
    pale[: int(height * 0.55)] = False
    categories["pale"] = groups_of(pale, 3, 3000)

    # The blue smears on the visor are lighter than the screen but not
    # pale, and they sit in the upper half of it.
    screen = (red < 100) & (green < 120) & (blue > 50) & (blue < 195)
    lighter = (blue > 105) & (red > 30) & (red < 120) & (green < 140)
    lighter = lighter & ~pale
    lighter[: int(height * 0.55)] = False
    categories["wisp"] = groups_of(lighter, 6, 4000)

    points = []
    for name, found in categories.items():
        for area, x0, y0, x1, y1, group in found:
            print("  %s area=%d box=%d,%d..%d,%d" % (name, area, x0, y0, x1, y1))
            step = max(1, len(group) // max_per_group) if max_per_group else 1
            for x, y in group:
                if step > 1 and (x * 31 + y * 17) % step:
                    continue
                points.append([int(x), int(y)])

    out = Path(sys.argv[2])
    out.write_text(json.dumps(points))
    print("YXZ_FIND points=%d" % len(points))


if __name__ == "__main__":
    main()
