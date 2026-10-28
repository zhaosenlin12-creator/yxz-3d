"""Put the YXZ artwork into the layer the canvas renders.

The figure is a 2D sprite: one picture for the body, small pictures for
the eyes and the mouth, and a glow over the halo.  The raised arm used
to be cut out of the body picture so that it could be turned around the
shoulder for a wave.

That cut was dropped on purpose.  A piece of a picture that is turned
around a joint always opens a seam at that joint: the pixels along the
edge of the cut stop lining up, and a bright hairline appears along the
arm every time it moves.  The arm therefore stays part of the body
picture, and the greeting is carried by the light on the hand instead.

This script keeps the body layer and the manifest in step with the
pristine artwork:

    body.png    the whole character: helmet, halo, arm and all
    manifest    where the layers sit, and where the palm is

Run from the repository root:

    python airi/scripts/yxz-layers/build_body.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
LAYERS = ROOT / "airi/packages/stage-ui/src/assets/yxz/layers"
SOURCE = ROOT / "airi/scripts/yxz-layers/body_pristine.png"

# The middle of the palm, which is where the sparkles come from.  It was
# read off the artwork: the hand is the white glove above the blue cuff.
HAND = (940.0, 700.0)


def build() -> dict:
    picture = Image.open(SOURCE).convert("RGBA")
    width, height = picture.size
    picture.save(LAYERS / "body.png")

    manifest = json.loads((LAYERS / "manifest.json").read_text(encoding="utf-8"))
    layers = manifest["layers"]
    # The arm is no longer a layer of its own.
    layers.pop("arm", None)
    layers.pop("socket", None)
    layers["hand"] = {"x": HAND[0], "y": HAND[1]}
    (LAYERS / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "body": "body.png",
        "width": width,
        "height": height,
        "hand": layers["hand"],
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
