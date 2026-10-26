"""Save the base-colour atlas out of a YXZ VRM without going via Blender.

The marks that still read as damage on the crown are painted into the
base-colour atlas, so the atlas itself is the place to find and measure
them.  The atlas can be pulled straight out of the GLB container, which
is much quicker and loses nothing compared with a Blender round trip.

Usage:
  python scripts/extract_yxz_atlas.py <source.vrm> <out-dir>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from glb_json import read_glb


def colour_images(document):
    for image in document.get("images", []):
        if image.get("name", "").startswith("Color_"):
            yield image


def image_bytes(document, binary, image):
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    return binary[start:start + view["byteLength"]]


def main():
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    document, binary = read_glb(source)
    for image in colour_images(document):
        payload = image_bytes(document, binary, image)
        picture = Image.open(io.BytesIO(payload)).convert("RGB")
        path = out / ("%s.png" % image["name"].replace("/", "_"))
        picture.save(path)
        print("YXZ_ATLAS_RAW wrote=%s size=%s bytes=%d"
              % (path, picture.size, len(payload)))

    print("YXZ_ATLAS_RAW materials=%s"
          % [m.get("name") for m in document.get("materials", [])])


if __name__ == "__main__":
    main()
