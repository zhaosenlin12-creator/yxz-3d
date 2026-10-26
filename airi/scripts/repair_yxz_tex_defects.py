"""Take the stray white paint off the dark blue of the visor.

The visor is the one dark panel on the front of the head.  The scan
painted two things on it that do not belong to it: a jagged white
crack, and a bar of white light across the middle.  Both are in the
texture, and on screen they read as broken glass, which is the
opposite of what a smooth moulded panel should look like.

They are found by shape as much as by colour.  The white of the
character's own shell is in big pieces -- a whole panel of the helmet
is white -- while paint that has been laid on top of the blue is in
small pieces with blue all around them.  So every piece of white in
the atlas is measured, and the small ones that sit in the middle of the
blue are the ones that are taken away.

Nothing is deleted outright.  Each mark is filled in with the blue
around it, the way a scratch in a moulded panel is filled and sanded
rather than left as a hole.

Usage:
  python scripts/repair_yxz_tex_defects.py <colour.png> <out.png> [--report]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(np.uint8)


def main() -> None:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    report_only = "--report" in sys.argv

    pixels = load(source)
    height, width = pixels.shape[:2]
    blue = pixels[:, :, 2].astype(np.int16)
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue

    white = ((luma > 185) & ((blue - red) < 26) & ((blue - green) < 26)).astype(np.uint8)
    # The dark blue of the visor and of the panels.
    navy = ((blue > red + 18) & (blue < 195) & (red < 140)).astype(np.uint8)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    marked = pixels.copy()
    taken = []
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < 12 or area > 6000:
            continue
        component = (labels == label).astype(np.uint8)
        # The blue has to be right there: a piece of white in the middle
        # of the blue is a mark on the panel, and a piece of white out in
        # the white is just the white.
        ring = cv2.dilate(component, np.ones((25, 25), np.uint8)) - cv2.dilate(
            component, np.ones((5, 5), np.uint8)
        )
        blue_share = float((navy * ring).sum()) / max(1.0, float(ring.sum()))
        if blue_share < 0.35:
            continue
        x = stats[label, cv2.CC_STAT_LEFT]
        y = stats[label, cv2.CC_STAT_TOP]
        w = stats[label, cv2.CC_STAT_WIDTH]
        h = stats[label, cv2.CC_STAT_HEIGHT]
        taken.append({"label": label, "area": int(area), "box": [int(x), int(y), int(w), int(h)],
                      "blueShare": round(blue_share, 3)})
        marked[component > 0] = (255, 0, 0)

    print("YXZ_TEX_MARKS", len(taken))
    for entry in sorted(taken, key=lambda e: -e["area"])[:40]:
        print("  ", entry)

    if report_only:
        Image.fromarray(marked).save(out)
        print("YXZ_TEX_REPORT", out)
        return

    mask = np.zeros((height, width), dtype=np.uint8)
    for entry in taken:
        x, y, w, h = entry["box"]
        mask[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3] = 1
    # Only the mark itself, not the blue around it.
    mask = (white & mask).astype(np.uint8)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    if mask.sum() == 0:
        Image.fromarray(pixels).save(out)
        print("YXZ_TEX_REPAIRED", out, "nothing to do")
        return
    healed = cv2.inpaint(pixels, mask, 6, cv2.INPAINT_TELEA)
    Image.fromarray(healed).save(out)
    print("YXZ_TEX_REPAIRED", out, "texels", int(mask.sum()))


if __name__ == "__main__":
    main()
