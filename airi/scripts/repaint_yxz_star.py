"""Take the magenta out of the star badge.

The scan's texture bake left a bright magenta streak lying across the
star on the forehead, and a pale pink patch in the middle of it.  The
star is the one piece of drawing on the character's face that the eye
goes to first, and a magenta streak across it is the single loudest
thing on the model -- it reads as a rendering fault rather than as a
colour.

Neither of them is a separate object: they are texels in the atlas
that belong to the star, wearing the wrong colour.  So they are
painted, not deleted, and they are painted with what is around them
rather than with a flat colour, so that the star's own shading runs
through them the way it runs through everything else.

The fill is a diffusion: every pixel of the defect takes the average of
its known neighbours, and the known area grows by a pixel at a time
until the defect is gone.  A streak that runs off the star and onto
the white helmet picks up the helmet on one end and the star on the
other, which is what makes it disappear instead of looking painted.

Usage:
  blender -b -P scripts/repaint_yxz_star.py -- \
    --source <glb> --output <glb> [--region x0,y0,x1,y1]
"""

from __future__ import annotations

import json
import sys

import bpy
import numpy as np


# The patch of the atlas the star badge is baked into.
#
# It is a rectangle rather than a shape because the streak has to be
# found by its colour and not by where it is: it runs off the star and
# onto the helmet, and a shape would have to know where it ends.
DEFAULT_REGION = (880, 3300, 1040, 3480)


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def defect_mask(region: np.ndarray) -> np.ndarray:
    """The texels wearing the wrong colour."""
    # The pixels come back as the bytes they were written as, so the
    # colours here are the colours in the atlas and the tests below are
    # the same tests the atlas was searched with.
    red = region[:, :, 0]
    green = region[:, :, 1]
    blue = region[:, :, 2]
    # The magenta: more red than green and more blue than green, which
    # is a colour nothing on this character is.
    strong = (red > green + 25) & (blue > green + 25) & (red > 110) & (green < 190)
    # The pale patch: a washed-out pink that is nearly white but is not
    # quite, and which the strong test misses because its blue is only
    # just above its green.
    pale = (red > 200) & (green > 150) & (blue > green + 12) & (blue < red - 12)
    return strong | pale


def fill(region: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Diffuse the surrounding colour into the defect."""
    out = region.copy()
    known = ~mask
    todo = mask.copy()
    for _ in range(256):
        if not todo.any():
            break
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        weights = np.pad(known.astype(np.float32), 1, mode="constant")
        total = np.zeros(out.shape, dtype=np.float32)
        count = np.zeros(mask.shape, dtype=np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                window = weights[
                    1 + dy:1 + dy + mask.shape[0],
                    1 + dx:1 + dx + mask.shape[1],
                ]
                total += padded[
                    1 + dy:1 + dy + mask.shape[0],
                    1 + dx:1 + dx + mask.shape[1],
                ] * window[..., None]
                count += window
        filled = todo & (count > 0)
        if not filled.any():
            break
        out[filled] = total[filled] / count[filled][..., None]
        known = known | filled
        todo = todo & ~filled
    return out


def main() -> None:
    source = value_after("--source")
    output = value_after("--output")
    region_arg = value_after("--region")
    x0, y0, x1, y1 = (
        [int(part) for part in region_arg.split(",")]
        if region_arg
        else DEFAULT_REGION
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    colour = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            colour = image
            break
    if colour is None:
        raise SystemExit("no colour image in the glb")
    width, height = colour.size
    pixels = np.empty(height * width * 4, dtype=np.float32)
    colour.pixels.foreach_get(pixels)
    image = pixels.reshape(height, width, 4)

    # The atlas is stored bottom row first, so the rectangle is taken
    # from the bottom of the image.
    rows = slice(height - y1, height - y0)
    columns = slice(x0, x1)
    patch = image[rows, columns, :3].copy() * 255.0
    mask = defect_mask(patch)
    if not mask.any():
        print("YXZ_STAR nothing to repaint")
        bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")
        return

    image[rows, columns, :3] = fill(patch, mask) / 255.0
    flat = image.reshape(-1, 4)
    colour.pixels.foreach_set(flat.ravel())
    try:
        colour.pack()
    except RuntimeError:
        pass

    print("YXZ_STAR " + json.dumps({
        "region": [x0, y0, x1, y1],
        "texels": int(mask.sum()),
    }))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


if __name__ == "__main__":
    main()
