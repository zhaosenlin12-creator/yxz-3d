"""Find the bright marks that are painted on the dark blue of the visor.

The visor is the one dark panel on the front of the head, and the scan
painted bright things on it: a jagged white crack that runs in from the
edge of the panel, and a bar of light across the middle.  On screen the
crack reads as broken glass, which is the opposite of what a smooth
moulded panel should look like.

They are in the atlas, not in the geometry, so they are found by colour
rather than by shape: a texel that is bright and almost colourless,
sitting in the middle of the dark blue of the panel, cannot be part of
the panel's paint.

The marks are written out as a picture over a copy of the atlas, so
what is about to be changed can be looked at before it is changed.

Usage:
  python scripts/detect_yxz_tex_defects.py <atlas.png> <out.png>
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def main() -> None:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    image = Image.open(source).convert("RGB")
    pixels = np.asarray(image).astype(np.float32) / 255.0
    height, width = pixels.shape[:2]
    r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    high = pixels.max(axis=2)
    low = pixels.min(axis=2)

    # The dark blue of the visor, and the blue panels elsewhere.
    navy = (b > r + 0.10) & (b < 0.78) & (r < 0.55)
    # Bright, and almost colourless: white paint.
    white = (luminance > 0.62) & ((high - low) < 0.10)
    # Bright and pink: the smear on the badge.
    pink = (r > g + 0.14) & (r > 0.30) & (b > g) & (b < r + 0.22)
    # The eyes are painted on the visor as pale cyan discs, so they say
    # where the visor is: the panel is the blue around them.
    cyan = (g > 0.70) & (b > 0.78) & (r < 0.72) & (g > r + 0.08)

    visor = np.zeros_like(navy)
    small = cyan[::4, ::4]
    rows, cols = small.shape
    seen = np.zeros_like(small)
    for y in range(rows):
        for x in range(cols):
            if not small[y, x] or seen[y, x]:
                continue
            queue = deque([(y, x)])
            seen[y, x] = True
            points = []
            while queue:
                cy, cx = queue.popleft()
                points.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < rows and 0 <= nx < cols and small[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
            if len(points) < 120:
                continue
            ys = [p[0] for p in points]
            xs = [p[1] for p in points]
            cy = int(sum(ys) / len(ys)) * 4
            cx = int(sum(xs) / len(xs)) * 4
            visor[max(0, cy - 620):cy + 620, max(0, cx - 620):cx + 620] = True

    # A texel is "in the middle of the blue" when every texel around it is
    # blue.  The white shell's edge against a blue panel is not: it has
    # white on one side of it.  Only paint that has been laid on top of
    # the blue has blue all the way round.
    surrounded = navy.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        shifted = np.roll(navy, (dy, dx), axis=(0, 1))
        surrounded &= shifted
    core = white & surrounded
    core = dilate(core, 5)
    crack = core & (white | ~navy)
    crack &= dilate(navy, 3)
    smear = pink & surrounded
    smear = dilate(smear, 3) & pink

    ys, xs = np.nonzero(crack)
    print("YXZ_TEX_CRACK", len(xs))
    if len(xs):
        print("  bbox", xs.min(), ys.min(), xs.max(), ys.max())
    ys, xs = np.nonzero(smear)
    print("YXZ_TEX_SMEAR", len(xs))
    if len(xs):
        print("  bbox", xs.min(), ys.min(), xs.max(), ys.max())

    marked = pixels.copy()
    marked[crack] = (1.0, 0.0, 0.0)
    marked[smear] = (0.0, 1.0, 0.0)
    Image.fromarray((marked * 255).astype(np.uint8)).save(out)
    print("YXZ_TEX_MARKED", out)


if __name__ == "__main__":
    main()
