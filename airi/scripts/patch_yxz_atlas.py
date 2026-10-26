"""Repair the marks on the YXZ base-colour atlas that survive the scan.

Three things are wrong with the visor as it comes out of the scan:

* A portrait of a face was printed on the original figure and the scan
  caught it.  Covering it left a flat patch of the wrong blue, which
  reads on screen as a blotch in the middle of the visor.
* A hard white line was left on the visor where the figure's own screen
  highlight was, and it reads as a crack rather than as a highlight.
* A few texels of the wrong blue were left where the painted eye was
  covered, in islands that are visible from the front.

Each repair works on the texels that are actually on screen, it fills
from the texture around the mark rather than with a flat colour, and it
writes out a crop of what it changed so the result can be looked at.

Usage:
  python scripts/patch_yxz_atlas.py <source.vrm> <out.vrm>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from glb_json import read_glb, write_glb


WRONG_BLUE = np.array([36, 71, 113])
VISOR = np.array([39, 63, 99])


def replace_image(document, binary, image_name, encoded):
    image_index = next(
        index for index, image in enumerate(document.get("images", []))
        if image.get("name") == image_name
    )
    image = document["images"][image_index]
    views = document["bufferViews"]
    blobs = []
    for view in views:
        start = view.get("byteOffset", 0)
        blobs.append(binary[start:start + view["byteLength"]])
    blobs[image["bufferView"]] = encoded
    offset = 0
    packed = bytearray()
    for view, blob in zip(views, blobs):
        padding = (-offset) % 4
        packed.extend(b"\x00" * padding)
        offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        packed.extend(blob)
        offset += len(blob)
    document["buffers"][0]["byteLength"] = len(packed)
    image["mimeType"] = "image/png"
    return bytes(packed)


def is_visor(patch):
    """True for texels that belong on the dark screen of the visor."""
    patch = np.asarray(patch).reshape(-1, 3).astype(int)
    red, green, blue = patch[:, 0], patch[:, 1], patch[:, 2]
    return (red < 110) & (blue > 55) & (blue < 200) & (green < 130)


def is_wrong_blue(patch):
    patch = np.asarray(patch).reshape(-1, 3).astype(int)
    return np.all(np.abs(patch - WRONG_BLUE.astype(int)) <= 2, axis=1)


def fill_from_above_and_below(pixels, mask, fallback):
    """Fill a mask with the texture that lies above and below it.

    The visor is a smooth gradient, so a patch of the wrong colour is
    repaired by continuing that gradient across it: each column is given
    the colour it has just above the patch and just below it, and the
    patch takes the line between the two.  A column that has no clean
    neighbour on either side takes the fallback, which is the colour of
    the ring around the patch.
    """
    height, width = mask.shape
    repaired = pixels.copy()
    for column in np.nonzero(mask.any(axis=0))[0]:
        rows = np.nonzero(mask[:, column])[0]
        top, bottom = int(rows[0]), int(rows[-1])
        above = pixels[top - 1, column] if top > 0 else None
        below = pixels[bottom + 1, column] if bottom + 1 < height else None
        if above is not None and not is_visor(above)[0]:
            above = None
        if below is not None and not is_visor(below)[0]:
            below = None
        if above is None and below is None:
            repaired[top:bottom + 1, column] = np.asarray(fallback, dtype=np.uint8)
            continue
        if above is None:
            repaired[top:bottom + 1, column] = np.asarray(below, dtype=np.uint8)
            continue
        if below is None:
            repaired[top:bottom + 1, column] = np.asarray(above, dtype=np.uint8)
            continue
        span = bottom - top + 1
        steps = (np.arange(span) + 1.0) / float(span + 1)
        ramp = (above[None, :].astype(float) * (1 - steps[:, None])
                + below[None, :].astype(float) * steps[:, None])
        repaired[top:bottom + 1, column] = ramp.round().astype(np.uint8)
    return repaired


def repair_wrong_blue(pixels):
    """Take the painted-over patches of the wrong blue off the visor."""
    match = np.all(np.abs(pixels.astype(int) - WRONG_BLUE.astype(int)) <= 2, axis=2)
    count, labels = cv2.connectedComponents(match.astype(np.uint8), 8)
    report = []
    for index in range(1, count):
        component = labels == index
        area = int(component.sum())
        if area < 120:
            continue
        ring = cv2.dilate(component.astype(np.uint8), np.ones((15, 15), np.uint8)) - component.astype(np.uint8)
        ring_pixels = pixels[ring > 0]
        if len(ring_pixels) == 0:
            continue
        visor_share = float(is_visor(ring_pixels).mean())
        if visor_share < 0.55:
            # This patch is not on the visor: it is the back of the head
            # or the inside of the helmet, and recolouring it there
            # would put a navy patch on the white shell.
            report.append("skip area=%d visor=%.2f" % (area, visor_share))
            continue
        grown = cv2.dilate(component.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        grown_pixels = pixels[grown]
        visor_pixels = grown_pixels[is_visor(grown_pixels) & ~is_wrong_blue(grown_pixels)]
        fallback = np.median(visor_pixels, axis=0) if len(visor_pixels) else VISOR
        pixels = fill_from_above_and_below(pixels, grown, fallback.astype(np.uint8))
        report.append("fix area=%d visor=%.2f fill=%s"
                      % (area, visor_share, [round(float(v), 1) for v in fallback]))
    return pixels, report


def repair_hard_highlight(pixels):
    """Take the hard white line off the visor.

    The line is a thin bright streak inside the dark screen.  It is found
    by being bright and by being surrounded by the dark screen, so the
    white shell of the helmet, which is bright and large, is not caught.
    """
    bright = (pixels[..., 0] > 150) & (pixels[..., 1] > 200) & (pixels[..., 2] > 220)
    count, labels = cv2.connectedComponents(bright.astype(np.uint8), 8)
    report = []
    for index in range(1, count):
        component = labels == index
        area = int(component.sum())
        if area < 8 or area > 600:
            continue
        rows = np.nonzero(component.any(axis=1))[0]
        columns = np.nonzero(component.any(axis=0))[0]
        height = int(rows[-1] - rows[0]) + 1
        width = int(columns[-1] - columns[0]) + 1
        if min(height, width) > 16 or area > 0.6 * height * width:
            # A bright mark that fills its own box is a shape, not a
            # scratch, and shapes are left alone.
            continue
        ring = cv2.dilate(component.astype(np.uint8), np.ones((9, 9), np.uint8)) - component.astype(np.uint8)
        ring_pixels = pixels[ring > 0]
        if len(ring_pixels) == 0:
            continue
        share = float(is_visor(ring_pixels).mean())
        if share < 0.85:
            # Only marks that sit wholly inside the dark screen are
            # repaired.  The white shell of the helmet is bright too, and
            # it is not a scratch.
            continue
        mask = component.astype(np.uint8)
        for _ in range(3):
            grown = cv2.dilate(mask, np.ones((3, 3), np.uint8))
            if int((grown > 0).sum()) == int((mask > 0).sum()):
                break
            mask = grown
        pixels = fill_from_above_and_below(pixels, mask > 0, VISOR)
        report.append("fix area=%d at %d,%d" % (area, columns[0], rows[0]))
    return pixels, report


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    document, binary = read_glb(source)
    image = next(item for item in document["images"]
                 if item.get("name", "").startswith("Color_"))
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    original = Image.open(io.BytesIO(binary[start:start + view["byteLength"]])).convert("RGB")
    pixels = np.asarray(original).copy()

    before = pixels.copy()
    pixels, blue_report = repair_wrong_blue(pixels)
    pixels, line_report = repair_hard_highlight(pixels)

    for entry in blue_report:
        print("YXZ_ATLAS wrong-blue %s" % entry)
    for entry in line_report:
        print("YXZ_ATLAS highlight %s" % entry)

    changed = np.any(before != pixels, axis=2)
    print("YXZ_ATLAS changed_texels=%d" % int(changed.sum()))
    if changed.any():
        ys, xs = np.nonzero(changed)
        print("YXZ_ATLAS changed_bbox x %d..%d y %d..%d"
              % (xs.min(), xs.max(), ys.min(), ys.max()))
        out = Path("docs/yxz-audit/atlas-patch")
        out.mkdir(parents=True, exist_ok=True)
        for name, box in (("visor", (1850, 3100, 2300, 3450)), ("edge", (1080, 3930, 1210, 4040))):
            x0, y0, x1, y1 = box
            crop = Image.fromarray(np.concatenate([
                before[y0:y1, x0:x1],
                pixels[y0:y1, x0:x1],
            ], axis=1)).resize(((x1 - x0) * 2, (y1 - y0) * 4), Image.LANCZOS)
            crop.save(out / ("%s.png" % name))

    encoded = io.BytesIO()
    Image.fromarray(pixels).save(encoded, format="PNG", optimize=False)
    packed = replace_image(document, binary, image["name"], encoded.getvalue())
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, packed)
    print("YXZ_ATLAS wrote=%s bytes=%d" % (output, len(encoded.getvalue())))


if __name__ == "__main__":
    main()
