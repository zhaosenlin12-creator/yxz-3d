"""Cut the raised arm of 宜小智 out of the body picture.

The pet is drawn as a 2D sprite, so the waving arm has to be a picture of
its own that can be turned around the shoulder.  The artwork is a single
render, so the arm is cut out of the pixels that are already there: no new
drawing, no repaint, and therefore no chance of the arm looking like it
belongs to a different robot.

Three pieces come out of one body picture:

  body.png    the character without the arm
  arm.png     the arm: shoulder, forearm, cuff and hand
  socket.png  the shoulder cap that covers the joint

The joint is a metal hinge, and a hinge is exactly what the artwork needs:
the arm turns around the middle of the hinge, and the cap that rides with
it is cut from the same pixels, so the two always agree.

Run from the repository root:

    python airi/scripts/yxz-layers/split_waving_arm.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
LAYERS = ROOT / "airi/packages/stage-ui/src/assets/yxz/layers"
SOURCE = ROOT / "airi/scripts/yxz-layers/body_pristine.png"

# The shoulder hinge, and the direction the arm runs in.  Both were read
# off the artwork: the hinge is the metal collar where the arm leaves the
# body, and the cuff sits on the same line.
PIVOT = np.array([836.0, 812.0])
CUFF = np.array([921.0, 755.0])

# The middle of the palm, which is where the sparkles of a wave come from.
HAND = np.array([940.0, 700.0])

# How much of the joint the cap has to cover.  The arm is cut along a line
# through the pivot, so the widest the cut can be is the width of the
# forearm there; the cap is a little wider so the joint never opens.
CAP_RADIUS = 58.0

# The cap fades out over this band.  It carries the same pixels as the arm,
# so a soft edge blends into the arm instead of drawing a ring on it.
CAP_FADE = 74.0

# The corridor the flood fill is allowed to travel in.  The arm runs
# forwards from the hinge and the body sits behind it, so a corridor along
# the arm keeps the fill from leaking into the chest.
CORRIDOR_BACK = 120.0
CORRIDOR_FRONT = 56.0


def _axis() -> tuple[np.ndarray, np.ndarray]:
    axis = CUFF - PIVOT
    axis = axis / np.linalg.norm(axis)
    perpendicular = np.array([-axis[1], axis[0]])
    return axis, perpendicular


def build() -> dict:
    picture = Image.open(SOURCE).convert("RGBA")
    data = np.asarray(picture).astype(np.float64)
    rgb, alpha = data[..., :3], data[..., 3]
    solid = alpha > 8

    axis, perpendicular = _axis()
    height, width = solid.shape
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    forward = (grid_x - PIVOT[0]) * axis[0] + (grid_y - PIVOT[1]) * axis[1]
    across = (grid_x - PIVOT[0]) * perpendicular[0] + (grid_y - PIVOT[1]) * perpendicular[1]

    # The flood starts on the glove and can only travel forwards from the
    # hinge, inside the corridor of the arm.
    walkable = solid & (forward >= 0) & (across >= -CORRIDOR_BACK) & (across <= CORRIDOR_FRONT)
    labels, _ = ndimage.label(walkable)
    arm = labels == labels[660, 960]
    if arm.sum() < 1000:
        raise SystemExit("the arm could not be found in the artwork")

    rows, columns = np.where(arm)
    box = (int(columns.min()), int(rows.min()), int(columns.max() - columns.min() + 1), int(rows.max() - rows.min() + 1))

    def layer(mask: np.ndarray) -> np.ndarray:
        cut = np.zeros((height, width, 4))
        cut[..., :3] = rgb
        cut[..., 3] = np.where(mask, alpha, 0)
        return cut[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]

    # The cap is the shoulder area of the arm itself, so it carries the
    # same pixels as the arm and the two can never disagree.  Its edge
    # fades out over a band that lies inside the arm, where the pixels are
    # the same anyway, so the fade leaves nothing behind.
    distance = np.hypot(grid_x - PIVOT[0], grid_y - PIVOT[1])
    fade = np.clip((CAP_FADE - distance) / (CAP_FADE - CAP_RADIUS), 0, 1)

    Image.fromarray(layer(arm).astype(np.uint8)).save(LAYERS / "arm.png")
    cap = np.zeros((height, width, 4))
    cap[..., :3] = rgb
    cap[..., 3] = np.where(arm, alpha * fade, 0)
    Image.fromarray(cap[box[1]:box[1] + box[3], box[0]:box[0] + box[2]].astype(np.uint8)).save(LAYERS / "socket.png")

    body = data.copy()
    body[..., 3] = np.where(arm, 0, alpha)
    Image.fromarray(body.astype(np.uint8)).save(LAYERS / "body.png")

    manifest = json.loads((LAYERS / "manifest.json").read_text(encoding="utf-8"))
    manifest["layers"]["arm"] = {
        "file": "arm.png",
        "x": box[0],
        "y": box[1],
        "w": box[2],
        "h": box[3],
        "pivotX": float(PIVOT[0]),
        "pivotY": float(PIVOT[1]),
        "handX": float(HAND[0]),
        "handY": float(HAND[1]),
    }
    manifest["layers"]["socket"] = {
        "file": "socket.png",
        "x": box[0],
        "y": box[1],
        "w": box[2],
        "h": box[3],
        "pivotX": float(PIVOT[0]),
        "pivotY": float(PIVOT[1]),
    }
    (LAYERS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest["layers"]["arm"]


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
