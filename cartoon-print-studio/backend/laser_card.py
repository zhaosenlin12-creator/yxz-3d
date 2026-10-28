# -*- coding: utf-8 -*-
"""Laser-cut card generation for the 宜小智 laser workflow.

Design contract (fixed for cutting):
  - Card size: every back template owns its size.  The 活动舞台 background is a
    16:9 banner, so its card is 16:9 as well (100 x 56.25 mm); the classic
    活动邀请 template keeps the business-card size (85.6 x 54 mm).  The SVG
    viewBox is in millimetres so xTool / LightBurn can open it directly.
  - Back side: a fixed template image (the activity artwork) is cover-fitted,
    rounded to 3 mm and given a 1 mm inner reference frame.
  - Front side: the artwork the visitor designed (their 3D model preview) plus
    the collected name / title / unit / contact / slogan.
  - SVG: outer cutting path (rounded rect rx=3 mm), 4 corner registration
    crosses, an inner engrave reference frame, the artwork as an embedded
    image layer and an engrave text layer.

Everything is deterministic and offline (PIL + SVG text), so the flow never
depends on a cloud image API.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# The template artwork ships with the repository (backend/assets/laser) so a
# fresh clone can cut a card without a separate asset pack.  At runtime the
# files are mirrored into <data>/laser/template, which is what the static
# /api/data/laser/template/<file> route serves.
PACKAGED_TEMPLATE_DIR = Path(__file__).resolve().parent / "assets" / "laser"
DATA_ROOT_HINT = Path(os.path.abspath(Path(__file__).resolve().parent.parent / "data"))


def ensure_templates(data_root: str) -> str:
    """Mirror the packaged back-side templates into the runtime data dir.

    Returns the template root that the HTTP layer should serve from.
    """
    target = Path(os.path.abspath(data_root)) / "laser" / "template"
    if not PACKAGED_TEMPLATE_DIR.is_dir():
        return str(target)

    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(PACKAGED_TEMPLATE_DIR.glob("*.png")):
        destination = target / source.name
        if not destination.is_file():
            shutil.copyfile(source, destination)
    return str(target)

# 10 px/mm
MM = 10
DEFAULT_CARD_MM = (85.6, 54.0)
CORNER_RADIUS_MM = 3.0

# Every back template carries its own card size, because the artwork decides
# the shape of the card.
TEMPLATE_SIZE_MM: dict[str, tuple[float, float]] = {
    "activity_stage": (100.0, 56.25),
    "activity_yichang": (100.0, 56.25),
}

TEMPLATE_NAMES: dict[str, str] = {
    "activity_blue": "宜小智 · 活动邀请",
    "activity_stage": "宜昌市第四届中小学生数理文化活动 · 舞台主视觉",
    "activity_yichang": "宜昌市第四届中小学生数理文化活动 · 三峡科技主视觉",
}

# Older templates that are superseded by the Yichang artwork.  They stay on
# disk (an already cut card can still reference them) but they are not
# offered in the picker any more.
TEMPLATE_HIDDEN: set[str] = {"activity_blue", "activity_stage"}

# The back face is a poster: the activity theme owns the centre in big type.
# It is typeset here (not baked into the artwork) so the template stays
# reusable and the title always matches the event.
DEFAULT_BACK_TITLE = "宜昌市第四届中小学生数理文化活动"
DEFAULT_BACK_TITLE_LINES = ("宜昌市第四届", "中小学生数理文化活动")
DEFAULT_BACK_SUBTITLE = "宜昌 · 数理 · 文化 · 科技"

# The front face is a poster too: the visitor's own artwork on top, the
# collected information on a solid bar underneath.
FRONT_ART_RATIO = 0.655

FONT_CANDIDATES = {
    "bold": [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ],
    "regular": [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ],
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_TEMPLATE_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def resolve_size_mm(back_template: str, template_root: str | None = None) -> tuple[float, float]:
    """Card size in millimetres for one back template.

    Templates that were generated on the fly (the visitor asked the AI for a
    background) carry their own size in the runtime registry.
    """
    if back_template in TEMPLATE_SIZE_MM:
        return TEMPLATE_SIZE_MM[back_template]
    entry = load_registry(template_root).get(back_template)
    if entry:
        try:
            return float(entry.get("width_mm", 100.0)), float(entry.get("height_mm", 56.25))
        except (TypeError, ValueError):
            pass
    return DEFAULT_CARD_MM


def registry_path(template_root: str | None) -> str:
    root = Path(template_root or (Path(os.path.abspath(DATA_ROOT_HINT)) / "laser" / "template"))
    return str(root / "templates.json")


def load_registry(template_root: str | None = None) -> dict[str, dict]:
    """Read the runtime registry of AI-generated back templates."""
    path = registry_path(template_root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def register_template(template_root: str, slug: str, name: str,
                      width_mm: float = 100.0, height_mm: float = 56.25,
                      side: str = "back") -> str:
    """Remember the display name and size of a generated template.

    ``side`` records whether the artwork belongs on the back of the card
    ("back") or was painted as the front artwork ("front"), so the studio can
    offer the right picker for each side.
    """
    registry = load_registry(template_root)
    registry[slug] = {
        "name": name,
        "width_mm": float(width_mm),
        "height_mm": float(height_mm),
        "side": "front" if side == "front" else "back",
    }
    path = registry_path(template_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(registry, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = FONT_CANDIDATES["bold" if bold else "regular"]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _hex_to_rgb(value: Optional[str], fallback: str) -> tuple[int, int, int]:
    raw = (value or "").strip()
    match = _HEX_RE.match(raw)
    if not match:
        raw = fallback
    raw = raw.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return mask


def _cover(image: Image.Image, w: int, h: int, focus_y: float = 0.5) -> Image.Image:
    """Cover-fit the image into w x h; ``focus_y`` biases the vertical crop.

    ``focus_y`` is 0 for "keep the top" and 1 for "keep the bottom", so a
    portrait artwork on a wide card can keep its subject in frame.
    """
    ratio = max(w / image.width, h / image.height)
    nw, nh = max(1, int(image.width * ratio)), max(1, int(image.height * ratio))
    resized = image.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    offset_y = int((h - nh) * focus_y)
    canvas.paste(resized, ((w - nw) // 2, offset_y))
    return canvas


def _scrim(image: Image.Image, theme: tuple[int, int, int], card_w: int, card_h: int,
           strength: float = 1.0) -> Image.Image:
    """Darken the artwork so the printed text stays readable on top of it.

    ``strength`` scales the whole gradient, so an AI-painted background can
    keep most of its artwork visible while a busy model render still gets a
    solid enough footer.
    """
    overlay = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    start = int(card_h * 0.36)
    for y in range(start, card_h):
        t = (y - start) / max(1, card_h - start)
        draw.line([(0, y), (card_w, y)], fill=(*theme, int(238 * strength * (t ** 1.25))))
    top = max(1, int(card_h * 0.14))
    for y in range(0, top):
        t = 1 - (y / top)
        draw.line([(0, y), (card_w, y)], fill=(*theme, int(78 * strength * t)))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _contain(image: Image.Image, w: int, h: int) -> Image.Image:
    """Fit the image inside w x h without cropping, centered on a soft plate."""
    ratio = min(w / image.width, h / image.height)
    nw, nh = max(1, int(image.width * ratio)), max(1, int(image.height * ratio))
    resized = image.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def _vertical_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        img.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img.resize((w, h))


def _fit_font_size(draw, lines: list[str], max_w: float, max_h: float,
                    bold: bool = True, max_size: int = 240, min_size: int = 8) -> int:
    """Largest font size whose block still fits inside ``max_w`` x ``max_h``."""
    low, high = min_size, max_size
    best = min_size
    while low <= high:
        mid = (low + high) // 2
        font = _font(mid, bold=bold)
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if widest <= max_w and len(lines) * mid * 1.24 <= max_h:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _draw_glow_text(image: Image.Image, xy: tuple[float, float], text: str,
                     font: ImageFont.FreeTypeFont, fill: tuple[int, int, int],
                     glow: tuple[int, int, int] = (120, 205, 255),
                     blur: int = 14, glow_alpha: int = 130) -> Image.Image:
    """Draw text with a soft coloured halo so it reads on any artwork."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=(*glow, glow_alpha))
    image = Image.alpha_composite(image.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(image).text(xy, text, font=font, fill=fill)
    return image


def _draw_tracked_text(draw, xy: tuple[float, float], text: str,
                       font: ImageFont.FreeTypeFont, fill, tracking: float = 0.0,
                       anchor: str = "lt") -> float:
    """Draw text letter by letter so it can breathe; returns the total width."""
    total = 0.0
    for char in text:
        total += draw.textlength(char, font=font) + tracking
    total = max(0.0, total - tracking)
    x, y = xy
    if anchor.startswith("m"):
        x -= total / 2
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking
    return total


def load_artwork(path: str) -> Optional[Image.Image]:
    """Load the visitor's own artwork (their model preview) for the card front."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as handle:
            return handle.convert("RGB")
    except Exception:
        return None


def _decorative_panel(w: int, h: int, theme: tuple[int, int, int],
                       accent: tuple[int, int, int], slogan: str) -> Image.Image:
    """The picture area of a front face that has no artwork yet.

    It is a quiet tech panel in the card theme, so the card still looks
    designed instead of empty while the visitor has not uploaded anything.
    """
    darker = tuple(max(0, int(v * 0.45)) for v in theme)
    panel = _vertical_gradient(w, h, theme, darker)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = int(w * 0.5), int(h * 0.52)
    for index, radius in enumerate((int(h * 0.20), int(h * 0.32), int(h * 0.46))):
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
                 200, 340, fill=(*accent, 120 - index * 30), width=3)
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
                 20, 160, fill=(255, 255, 255, 46 - index * 12), width=2)
    for index in range(46):
        x = (index * 97) % max(1, w)
        y = (index * 53) % max(1, h)
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 255, 255, 60))
    panel = Image.alpha_composite(panel.convert("RGBA"), layer).convert("RGB")

    if slogan:
        draw = ImageDraw.Draw(panel)
        size = max(10, int(h * 0.13))
        font = _font(size, bold=False)
        width = draw.textlength(slogan, font=font)
        draw.text(((w - width) / 2, int(h * 0.60)), slogan, font=font, fill=(226, 240, 255))
    return panel


def render_front(spec: dict[str, Any], size_mm: tuple[float, float],
                 artwork: Optional[Image.Image] = None,
                 front_art: Optional[Image.Image] = None) -> Image.Image:
    """Render the editable front of the card.

    The front is a poster: the visitor's own artwork (their 2D preview) fills
    the upper part and a solid information bar underneath carries the name,
    the identity / school and the contact.  Splitting the card in half with
    the artwork on one side read as two unrelated pieces, so the artwork now
    owns the stage and the information sits on a clean bar.
    """
    width_mm, height_mm = size_mm
    card_w = max(1, int(width_mm * MM))
    card_h = max(1, int(height_mm * MM))
    corner_radius = int(CORNER_RADIUS_MM * MM)

    theme = _hex_to_rgb(spec.get("theme"), "#0B5FA8")
    accent = _hex_to_rgb(spec.get("accent"), "#F5A623")
    white = (255, 255, 255)
    soft = (235, 244, 255)

    slogan = (spec.get("slogan") or "").strip()
    name = (spec.get("name") or "").strip() or "姓名"
    title_text = (spec.get("title") or "").strip()
    unit_text = (spec.get("unit") or "").strip()
    line1 = " ".join(x for x in (title_text, unit_text) if x)
    contact = (spec.get("contact") or "").strip()
    note = (spec.get("note") or "").strip()

    darker = tuple(max(0, int(v * 0.48)) for v in theme)

    art_h = max(1, int(card_h * FRONT_ART_RATIO))
    info_h = max(1, card_h - art_h)

    face = artwork if artwork is not None else front_art
    if face is not None:
        # Cover-fit into the picture area only; the information bar below is
        # solid, so the artwork never has to fight the text.
        picture = _cover(face, card_w, art_h, focus_y=0.45)
    else:
        picture = _decorative_panel(card_w, art_h, theme, accent, slogan)

    # --- the information bar ---------------------------------------------
    bar = _vertical_gradient(card_w, info_h, theme, darker)
    canvas = Image.new("RGB", (card_w, card_h))
    canvas.paste(picture, (0, 0))
    canvas.paste(bar, (0, art_h))
    draw = ImageDraw.Draw(canvas)

    pad_x = int(card_w * 0.055)
    accent_w = max(3, int(info_h * 0.035))
    name_size = int(info_h * 0.30)
    info_size = int(info_h * 0.135)
    contact_size = int(info_h * 0.118)

    name_font = _font(max(16, name_size), bold=True)
    info_font = _font(max(10, info_size), bold=False)
    contact_font = _font(max(9, contact_size), bold=False)

    left_x = pad_x + accent_w + int(info_h * 0.09)
    name_y = art_h + int(info_h * 0.14)

    # accent tick in front of the name
    draw.rounded_rectangle(
        (pad_x, name_y + int(name_size * 0.08), pad_x + accent_w, name_y + int(name_size * 1.02)),
        radius=accent_w,
        fill=accent,
    )
    draw.text((left_x, name_y), name, font=name_font, fill=white)

    meta_y = name_y + int(name_size * 1.16)
    if line1:
        draw.text((left_x, meta_y), line1, font=info_font, fill=soft)
        meta_y += int(info_size * 1.45)
    # Without artwork the slogan already sits in the picture panel, so it is
    # only repeated in the bar when the picture is the visitor's own work.
    if slogan and face is not None:
        draw.text((left_x, meta_y), slogan, font=info_font, fill=soft)

    # right column: the contact details, right aligned
    contact_lines = [x.strip() for x in contact.splitlines() if x.strip()][:2]
    right_x = card_w - pad_x
    y = art_h + info_h - int(info_h * 0.16) - len(contact_lines) * int(contact_size * 1.42)
    for line in contact_lines:
        width = draw.textlength(line, font=contact_font)
        draw.text((right_x - width, y), line, font=contact_font, fill=white)
        y += int(contact_size * 1.42)

    if note:
        note_font = _font(max(9, int(info_size * 0.86)), bold=False)
        width = draw.textlength(note, font=note_font)
        draw.text((right_x - width, art_h + info_h - int(info_h * 0.20)), note, font=note_font, fill=soft)

    rounded = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    rounded.paste(canvas, (0, 0), _rounded_mask(card_w, card_h, corner_radius))
    return rounded.convert("RGB")


def render_back(template_path: str, spec: dict[str, Any], size_mm: tuple[float, float]) -> Image.Image:
    """Render the fixed back face: the activity poster.

    The theme is typeset big in the middle of the artwork, so the card
    reads as "this is the activity card" at a glance.  The type is drawn
    here rather than baked into the template so the same artwork can serve
    a different event.
    """
    width_mm, height_mm = size_mm
    card_w = max(1, int(width_mm * MM))
    card_h = max(1, int(height_mm * MM))
    corner_radius = int(CORNER_RADIUS_MM * MM)
    unit = card_h / 540.0

    base = Image.open(template_path).convert("RGB")
    background = _cover(base, card_w, card_h)

    accent = _hex_to_rgb(spec.get("accent"), "#F5A623")
    title_lines = _back_title_lines(spec)
    measure = ImageDraw.Draw(background)
    title_size = _fit_font_size(measure, title_lines, card_w * 0.84, card_h * 0.40)
    title_font = _font(title_size, bold=True)
    line_h = title_size * 1.24
    block_h = line_h * len(title_lines)
    center_y = card_h * 0.33

    # A calm band behind the title keeps it legible on any artwork.
    scrim = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    band_h = int(block_h * 2.05)
    ImageDraw.Draw(scrim).rounded_rectangle(
        (int(card_w * 0.035), int(center_y - band_h / 2),
         int(card_w * 0.965), int(center_y + band_h / 2)),
        radius=int(card_h * 0.07),
        fill=(2, 10, 24, 135),
    )
    scrim = scrim.filter(ImageFilter.GaussianBlur(max(2, int(card_h * 0.045))))
    background = Image.alpha_composite(background.convert("RGBA"), scrim).convert("RGB")

    y = center_y - block_h / 2
    for line in title_lines:
        width = measure.textlength(line, font=title_font)
        background = _draw_glow_text(
            background, ((card_w - width) / 2, y), line, title_font,
            (255, 255, 255), glow=(126, 206, 255),
            blur=max(5, int(title_size * 0.11)), glow_alpha=140,
        )
        y += line_h

    draw = ImageDraw.Draw(background)

    # accent rule + subtitle under the title
    rule_y = center_y + block_h / 2 + title_size * 0.26
    rule_w = title_size * 1.7
    draw.rounded_rectangle(
        ((card_w - rule_w) / 2, rule_y, (card_w + rule_w) / 2, rule_y + max(2, int(title_size * 0.055))),
        radius=3, fill=accent,
    )
    subtitle = (spec.get("back_subtitle") or "").strip() or DEFAULT_BACK_SUBTITLE
    sub_size = max(10, int(title_size * 0.24))
    sub_font = _font(sub_size, bold=False)
    _draw_tracked_text(
        draw, (card_w / 2, rule_y + title_size * 0.20), subtitle, sub_font,
        fill=(214, 236, 255), tracking=sub_size * 0.14, anchor="mt",
    )

    frame = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(frame)
    fdraw.rounded_rectangle(
        (int(14 * unit), int(14 * unit), card_w - int(14 * unit), card_h - int(14 * unit)),
        radius=max(2, corner_radius - 5),
        outline=(255, 255, 255, 220),
        width=max(2, int(4 * unit)),
    )
    background = Image.alpha_composite(background.convert("RGBA"), frame).convert("RGB")

    rounded = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    rounded.paste(background, (0, 0), _rounded_mask(card_w, card_h, corner_radius))
    return rounded.convert("RGB")


def _back_title_lines(spec: dict[str, Any]) -> list[str]:
    """The activity theme, split into the lines that will be typeset."""
    raw = spec.get("back_title")
    if isinstance(raw, (list, tuple)):
        lines = [str(x).strip() for x in raw if str(x).strip()]
        if lines:
            return lines
    title = (str(raw).strip() if raw else "") or DEFAULT_BACK_TITLE
    if title == DEFAULT_BACK_TITLE:
        return list(DEFAULT_BACK_TITLE_LINES)
    if len(title) <= 8:
        return [title]
    # Split into two balanced lines that stay readable as a headline.
    middle = len(title) // 2
    return [title[:middle].strip(), title[middle:].strip()]


def _svg_rounded_rect(x: float, y: float, w: float, h: float, r: float, fill: str, stroke: str, stroke_width: float) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
    )


def _embed_image_data_uri(path: str, max_width: int = 1000) -> str:
    """Inline the artwork so the cut file stays a single portable document.

    The image is re-encoded at a bounded width: the original preview is far
    larger than the engraved area needs, and an oversized SVG is slow to open
    in the laser software.
    """
    if not path or not os.path.isfile(path):
        return ""
    try:
        with Image.open(path) as handle:
            image = handle.convert("RGB")
            if image.width > max_width:
                ratio = max_width / image.width
                image = image.resize((max_width, max(1, int(image.height * ratio))), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return ""
    return f"data:image/png;base64,{payload}"


def build_svg(
    spec: dict[str, Any],
    size_mm: tuple[float, float],
    engrave_text: str = "",
    artwork_path: str = "",
    back_art_path: str = "",
) -> str:
    """Cut file in millimetres. Layers:
      - outer cut (red, thin): the physical card outline
      - corner registration crosses (dashed thin)
      - inner engrave reference frame (green, thin)
      - artwork image layer (the visitor's model, embedded) in the picture
        area, matching the printed front
      - the back artwork layer, so both faces of the card are in one file
      - optional engrave text (blue, converted to paths is left to the tool)
    """
    width_mm, height_mm = size_mm
    x, y, w, h = 0.0, 0.0, width_mm, height_mm
    r = CORNER_RADIUS_MM
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" viewBox="0 0 {width_mm} {height_mm}">',
        "  <!-- 外切割轮廓（红色） -->",
        _svg_rounded_rect(x, y, w, h, r, "none", "#FF0000", 0.25),
        "  <!-- 内框雕刻参考线（绿色） -->",
        _svg_rounded_rect(x + 1.2, y + 1.2, w - 2.4, h - 2.4, max(0.5, r - 0.6), "none", "#00A000", 0.15),
        "  <!-- 四角定位十字 -->",
    ]
    for cx, cy in ((2.5, 2.5), (w - 2.5, 2.5), (2.5, h - 2.5), (w - 2.5, h - 2.5)):
        lines.append(
            f'<path d="M {cx - 1.6} {cy} H {cx + 1.6} M {cx} {cy - 1.6} V {cy + 1.6}" '
            f'fill="none" stroke="#FF0000" stroke-width="0.15"/>'
        )

    art_h = h * FRONT_ART_RATIO
    data_uri = _embed_image_data_uri(artwork_path)
    if data_uri:
        lines.append("  <!-- 正面作品图（与正面预览一致，可雕刻或打印） -->")
        lines.append(
            f'<image x="1.2" y="1.2" width="{w - 2.4:.2f}" height="{art_h - 2.4:.2f}" '
            f'preserveAspectRatio="xMidYMid slice" href="{data_uri}"/>'
        )

    back_uri = _embed_image_data_uri(back_art_path, max_width=1200)
    if back_uri:
        lines.append("  <!-- 背面活动主视觉（翻面雕刻时启用此图层） -->")
        lines.append(
            f'<image x="1.2" y="1.2" width="{w - 2.4:.2f}" height="{h - 2.4:.2f}" '
            f'preserveAspectRatio="xMidYMid slice" href="{back_uri}"/>'
        )

    theme = _hex_to_rgb(spec.get("theme"), "#0B5FA8")
    engrave = (engrave_text or "").strip() or (spec.get("name") or "").strip()
    if engrave:
        lines.append("  <!-- 姓名雕刻文字（蓝色，可在软件中转换为路径） -->")
        lines.append(
            f'<text x="{w / 2:.2f}" y="{h - 4:.2f}" text-anchor="middle" '
            f'font-family="Microsoft YaHei, SimHei, sans-serif" font-size="5" '
            f'fill="#0040FF" fill-opacity="0.9">{_xml_escape(engrave)}</text>'
        )
    lines.append(
        f'  <text x="{w - 2:.2f}" y="{h - 1.5:.2f}" text-anchor="end" font-size="1.2" '
        f'fill="#888888">{width_mm:g} × {height_mm:g} mm · 0.2–3 mm 板材请按实际校准</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _safe_slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", text or "")
    return cleaned if cleaned else fallback


def generate(
    spec: dict[str, Any],
    data_root: str,
    template_root: str | None = None,
) -> dict[str, Any]:
    """Render front/back/preview PNGs and the cut SVG under
    data_root/laser/<sid>/. Returns absolute paths."""
    data_root = os.path.abspath(data_root)
    template_root = template_root or ensure_templates(data_root)
    back_template = (spec.get("back_template") or "activity_yichang").strip()
    if not _TEMPLATE_SLUG_RE.match(back_template):
        back_template = "activity_yichang"
    template_path = os.path.join(template_root, f"{back_template}.png")
    if not os.path.isfile(template_path):
        template_path = os.path.join(template_root, "activity_yichang.png")
    if not os.path.isfile(template_path):
        template_path = os.path.join(template_root, "activity_stage.png")
    if not os.path.isfile(template_path):
        # Last resort: the templates that ship with the repository.
        template_path = os.path.join(str(PACKAGED_TEMPLATE_DIR), "activity_yichang.png")
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"名片背面模板缺失：{template_path}")
    back_template = os.path.splitext(os.path.basename(template_path))[0]

    size_mm = resolve_size_mm(back_template, template_root)
    card_w = max(1, int(size_mm[0] * MM))
    card_h = max(1, int(size_mm[1] * MM))

    sid = _safe_slug(str(spec.get("session_id") or uuid.uuid4().hex[:12]), uuid.uuid4().hex[:12])
    out_dir = os.path.join(data_root, "laser", sid)
    os.makedirs(out_dir, exist_ok=True)

    artwork_path = str(spec.get("artwork_path") or "")
    artwork = load_artwork(artwork_path)

    front_art = _load_front_art(spec.get("front_template"), template_root)

    front = render_front(spec, size_mm, artwork, front_art)
    back = render_back(template_path, spec, size_mm)
    front_path = os.path.join(out_dir, "card_front.png")
    back_path = os.path.join(out_dir, "card_back.png")
    front.save(front_path)
    back.save(back_path)

    # Preview: the front on top, the back underneath.  Stacked reads as one
    # card at a glance, while side by side shrank both faces into a strip.
    margin = 30
    label_h = 46
    gap = 34
    preview = Image.new(
        "RGB",
        (card_w + margin * 2, margin * 2 + label_h * 2 + card_h * 2 + gap),
        (236, 242, 247),
    )
    pdraw = ImageDraw.Draw(preview)
    label_font = _font(28, bold=True)
    faces = (
        ("正面 · 你的作品", front),
        ("背面 · 活动主题", back),
    )
    y = margin
    for label, face in faces:
        pdraw.text((margin, y), label, font=label_font, fill=(28, 66, 104))
        y += label_h
        face_rgba = face.convert("RGBA")
        preview.paste(face_rgba, (margin, y), face_rgba)
        pdraw.rectangle((margin - 1, y - 1, margin + card_w, y + card_h),
                        outline=(126, 168, 196), width=2)
        y += card_h + gap
    png_path = os.path.join(out_dir, "card.png")
    preview.save(png_path)

    svg_path = os.path.join(out_dir, "card.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(build_svg(
            spec, size_mm, artwork_path=artwork_path, back_art_path=template_path,
        ))

    return {
        "session_id": sid,
        "svg_path": svg_path,
        "png_path": png_path,
        "front_path": front_path,
        "back_path": back_path,
        "back_template": back_template,
        "front_template": (spec.get("front_template") or "").strip(),
        "has_artwork": artwork is not None,
        "has_front_art": front_art is not None,
        "size_mm": {"width": size_mm[0], "height": size_mm[1]},
    }


def _load_front_art(front_template: Any, template_root: str) -> Optional[Image.Image]:
    """Load the AI-painted artwork registered for the front of the card."""
    slug = str(front_template or "").strip()
    if not slug or not _TEMPLATE_SLUG_RE.match(slug):
        return None
    path = os.path.join(template_root, f"{slug}.png")
    if not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as handle:
            return handle.convert("RGB")
    except Exception:
        return None


def list_templates(template_root: str) -> list[dict[str, Any]]:
    root = Path(template_root)
    items: list[dict[str, Any]] = []
    if not root.is_dir():
        return items
    registry = load_registry(template_root)
    for path in sorted(root.glob("*.png")):
        slug = path.stem
        if not _TEMPLATE_SLUG_RE.match(slug):
            continue
        if slug in TEMPLATE_HIDDEN:
            continue
        entry = registry.get(slug) or {}
        width_mm, height_mm = resolve_size_mm(slug, template_root)
        items.append({
            "id": slug,
            "name": entry.get("name") or TEMPLATE_NAMES.get(slug, slug),
            "url": f"/api/data/laser/template/{path.name}",
            "preview_url": f"/api/laser/template-preview/{slug}",
            "size_mm": {"width": width_mm, "height": height_mm},
            "generated": bool(entry),
            "side": entry.get("side") or "back",
        })
    return items


_PREVIEW_CACHE: dict[str, tuple[float, bytes]] = {}


def render_template_preview(template_root: str, slug: str,
                            title: str = "", subtitle: str = "",
                            accent: str = "#F5A623") -> bytes:
    """Render the back face of one template with the activity theme on it.

    The picker shows this instead of the raw artwork, so the visitor sees
    exactly what the finished card back will look like.
    """
    if not _TEMPLATE_SLUG_RE.match(slug or ""):
        return b""
    path = os.path.join(template_root, f"{slug}.png")
    if not os.path.isfile(path):
        return b""

    key = f"{slug}|{os.path.getmtime(path):.0f}|{title}|{subtitle}|{accent}"
    cached = _PREVIEW_CACHE.get(key)
    if cached:
        return cached[1]

    size_mm = resolve_size_mm(slug, template_root)
    spec = {"back_title": title, "back_subtitle": subtitle, "accent": accent}
    image = render_back(path, spec, size_mm)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    _PREVIEW_CACHE[key] = (os.path.getmtime(path), payload)
    return payload
