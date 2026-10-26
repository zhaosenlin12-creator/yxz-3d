"""Cut a piece out of the atlas so it can be looked at closely.

The atlas is four thousand pixels square and holds every part of the
character at once, so nothing in it can be judged until it is magnified.
This takes a rectangle in atlas coordinates and writes it out as its own
picture, which is how a mark on the model is traced back to the place in
the picture it came from.

Usage:
  python scripts/crop_yxz_atlas.py --atlas <png> --out <png> \
    --uv 0.30,0.20,0.45,0.40 [--zoom 2]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atlas", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--uv", required=True,
                        help="u0,v0,u1,v1 in atlas coordinates")
    parser.add_argument("--zoom", type=int, default=1)
    args = parser.parse_args()

    image = Image.open(args.atlas).convert("RGB")
    width, height = image.size
    u0, v0, u1, v1 = [float(p) for p in args.uv.split(",")]
    x0 = int(min(u0, u1) * width)
    x1 = int(max(u0, u1) * width)
    # The atlas is stored bottom to top, so a crop's top is its largest v.
    y0 = int((1.0 - max(v0, v1)) * height)
    y1 = int((1.0 - min(v0, v1)) * height)
    x0 = max(0, min(width - 1, x0))
    x1 = max(x0 + 1, min(width, x1))
    y0 = max(0, min(height - 1, y0))
    y1 = max(y0 + 1, min(height, y1))

    crop = image.crop((x0, y0, x1, y1))
    if args.zoom > 1:
        size = (crop.width * args.zoom, crop.height * args.zoom)
        crop = crop.resize(size, Image.NEAREST)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    crop.save(args.out)
    print("YXZ_CROP %s %dx%d from %d,%d" % (args.out, crop.width, crop.height,
                                           x0, y0))


if __name__ == "__main__":
    main()
