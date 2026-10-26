"""Patch the known dark visor atlas blemish without round-tripping the VRM.

The blemish is a patch of paint in a slightly different blue from the
visor it sits on, with a jagged edge, and it is the shape of a face that
was painted into the scan and then covered with the visor's colour.  The
colour it was covered with does not match the visor around it, so the
cover reads as a blotch.

The patch is found by its colour and by its connectedness, not by a
hand-drawn polygon: a polygon drawn by eye reaches across the boundary
into the white of the helmet and repairs the blotch by putting a white
smear on the visor instead.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from glb_json import read_glb, write_glb


def replace_image(document, binary, image_name, edited):
    image_index = next(
        index for index, image in enumerate(document.get("images", []))
        if image.get("name") == image_name
    )
    image = document["images"][image_index]
    view_index = image["bufferView"]
    views = document["bufferViews"]
    blobs = []
    for index, view in enumerate(views):
        start = view.get("byteOffset", 0)
        blobs.append(binary[start:start + view["byteLength"]])

    blobs[view_index] = edited
    offset = 0
    packed = bytearray()
    for index, (view, blob) in enumerate(zip(views, blobs)):
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

    # The colour of the blotch, and the colour of the visor around it.
    blotch = np.array([36, 71, 113])
    visor = np.array([39, 63, 99])
    # The window the blotch was measured in, in image pixels.
    window = (2100, 3200, 2300, 3450)
    x0, y0, x1, y1 = window

    def close_to(patch, colour, tolerance):
        return np.all(np.abs(patch.astype(int) - colour.astype(int)) <= tolerance, axis=2)

    # A mask of the blotch's colour, grown a little so that the texels
    # along the ragged edge are included.
    seed = close_to(pixels[y0:y1, x0:x1], blotch, 2)
    seed_u8 = seed.astype(np.uint8)
    count, labels = cv2.connectedComponents(seed_u8, 8)
    if count < 2:
        print("YXZ_VISOR_PATCH no blotch found")
        return
    sizes = [(int((labels == index).sum()), index) for index in range(1, count)]
    sizes.sort(reverse=True)
    largest = sizes[0][1]
    blotch_mask = np.zeros(pixels.shape[:2], np.uint8)
    blotch_mask[y0:y1, x0:x1] = (labels == largest).astype(np.uint8)
    # Grow it by a couple of texels to take the anti-aliased edge with it.
    blotch_mask = cv2.dilate(blotch_mask, np.ones((5, 5), np.uint8))

    # Fill the blotch with the visor's own colour, using the texture
    # around it as the source, so the result is the visor rather than a
    # flat patch of paint.
    ring = cv2.dilate(blotch_mask, np.ones((21, 21), np.uint8)) - blotch_mask
    source = cv2.inpaint(pixels, blotch_mask, 12, cv2.INPAINT_TELEA)
    # The visor around the blotch is very slightly graded, so the fill is
    # taken from the ring rather than from a single flat colour.
    ring_pixels = pixels[ring > 0]
    if len(ring_pixels) == 0:
        ring_pixels = visor.reshape(1, 3)
    fill = np.median(ring_pixels, axis=0)
    pixels[blotch_mask > 0] = fill
    repaired = source
    print("YXZ_VISOR_PATCH texels=%d fill=%s"
          % (int(blotch_mask.sum()), [round(float(v), 1) for v in fill]))

    # Inpaint only the wrong polygon. The surrounding visor colour stays
    # untouched, including the nearby white helmet boundary.
    encoded = io.BytesIO()
    Image.fromarray(repaired).save(encoded, format="PNG", optimize=False)
    packed = replace_image(document, binary, image["name"], encoded.getvalue())
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, packed)
    print(f"YXZ_VISOR_PATCH bytes={len(encoded.getvalue())}")


if __name__ == "__main__":
    main()
