"""Tell a multi-pose sheet apart from a single design.

Some image providers answer "give me four views of this character" with a
contact sheet: nine poses of the same figure in one square picture.  A 3D
builder reads that square as one object and copies the whole grid, so the
visitor gets a model of nine robots instead of the design they picked.

When the picture really is a sheet, the single biggest figure in it is the
design that was meant, so the build works from that figure alone.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

try:  # Pillow is optional: without it the build just uses the whole picture.
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is a hard dependency in practice
    Image = None  # type: ignore[assignment]


# A figure has to be this tall (share of the picture height) to count as a
# pose of the character.  A logo or a floating decoration is smaller.
MIN_FIGURE_HEIGHT = 0.20
# ...and this wide, so a thin stroke is not mistaken for a figure.
MIN_FIGURE_WIDTH = 0.05
# A picture with fewer poses than this is one design, not a sheet.
MIN_FIGURES = 3
# The background has to be light.  A product photo on a grey sweep is one
# object, however many highlights it has.
MAX_INK_RATIO = 0.72
# The picture is shrunk to this size before it is analysed: the shapes are
# what matter, not the pixels.
ANALYSIS_SIDE = 256


def _components(mask: bytearray, width: int, height: int) -> List[Tuple[int, int, int, int, int]]:
    """Group the marked pixels into connected shapes.

    Returns ``(area, x0, y0, x1, y1)`` for every shape.
    """
    seen = bytearray(width * height)
    shapes: List[Tuple[int, int, int, int, int]] = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        area = 0
        x0 = x1 = start % width
        y0 = y1 = start // width
        while stack:
            index = stack.pop()
            area += 1
            x = index % width
            y = index // width
            if x < x0:
                x0 = x
            if x > x1:
                x1 = x
            if y < y0:
                y0 = y
            if y > y1:
                y1 = y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbour = ny * width + nx
                    if mask[neighbour] and not seen[neighbour]:
                        seen[neighbour] = 1
                        stack.append(neighbour)
        shapes.append((area, x0, y0, x1, y1))
    return shapes


def find_subject_box(path: str) -> Optional[Tuple[int, int, int, int]]:
    """The crop box of the biggest figure when the picture is a pose sheet.

    ``None`` means the picture is a single design and has to be used as it
    is.
    """
    if Image is None or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as opened:
            picture = opened.convert("RGB")
            original_width, original_height = picture.size
            if not original_width or not original_height:
                return None
            scale = ANALYSIS_SIDE / float(max(original_width, original_height))
            small = picture.resize(
                (max(1, int(original_width * scale)), max(1, int(original_height * scale))),
                Image.BILINEAR,
            )
    except Exception:
        return None

    width, height = small.size
    pixels = small.load()
    mask = bytearray(width * height)
    ink = 0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            # Near-white is background.  A soft shadow on white stays light
            # enough to be background as well.
            if red < 236 or green < 236 or blue < 236:
                mask[y * width + x] = 1
                ink += 1
    if ink > MAX_INK_RATIO * width * height:
        return None

    figures = []
    for area, x0, y0, x1, y1 in _components(mask, width, height):
        figure_height = (y1 - y0 + 1) / float(height)
        figure_width = (x1 - x0 + 1) / float(width)
        if (figure_height >= MIN_FIGURE_HEIGHT
                and figure_width >= MIN_FIGURE_WIDTH
                and area >= 0.01 * width * height):
            figures.append((area, x0, y0, x1, y1))
    if len(figures) < MIN_FIGURES:
        return None

    # The biggest figure is the one the visitor looks at first.
    area, x0, y0, x1, y1 = max(figures, key=lambda item: item[0])
    # A square around it, so the figure ends up centred in the crop.
    side = max(x1 - x0 + 1, y1 - y0 + 1)
    centre_x = (x0 + x1 + 1) // 2
    centre_y = (y0 + y1 + 1) // 2
    left = max(0, centre_x - side // 2)
    top = max(0, centre_y - side // 2)
    left = min(left, width - side) if width > side else 0
    top = min(top, height - side) if height > side else 0
    side = min(side, width, height)
    right = min(width, left + side)
    bottom = min(height, top + side)
    if right - left < 8 or bottom - top < 8:
        return None

    factor_x = original_width / float(width)
    factor_y = original_height / float(height)
    box = (
        int(left * factor_x),
        int(top * factor_y),
        int(right * factor_x),
        int(bottom * factor_y),
    )
    if box[2] - box[0] < 16 or box[3] - box[1] < 16:
        return None
    return box


def crop_to_subject(src_path: str, dst_path: str) -> Optional[str]:
    """Write the single figure of a pose sheet to ``dst_path``.

    ``None`` means the picture was not a sheet and must be used unchanged.
    """
    if Image is None:
        return None
    box = find_subject_box(src_path)
    if not box:
        return None
    try:
        with Image.open(src_path) as opened:
            picture = opened.convert("RGB")
            subject = picture.crop(box)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            subject.save(dst_path, format="PNG")
    except Exception:
        return None
    return dst_path


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import sys

    for candidate in sys.argv[1:]:
        print(candidate, "->", find_subject_box(candidate))
