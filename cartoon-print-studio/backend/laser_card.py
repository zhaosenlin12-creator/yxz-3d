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

from PIL import Image, ImageDraw, ImageFont

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
}

TEMPLATE_NAMES: dict[str, str] = {
    "activity_blue": "宜小智 · 活动邀请",
    "activity_stage": "宜昌市第四届中小学生数理文化活动 · 舞台主视觉",
}

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


def load_artwork(path: str) -> Optional[Image.Image]:
    """Load the visitor's own artwork (their model preview) for the card front."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as handle:
            return handle.convert("RGB")
    except Exception:
        return None


def render_front(spec: dict[str, Any], size_mm: tuple[float, float],
                 artwork: Optional[Image.Image] = None,
                 front_art: Optional[Image.Image] = None) -> Image.Image:
    """Render the editable front of the card.

    ``artwork`` is the model preview the visitor produced; ``front_art`` is an
    AI-painted card face.  Either one turns the front into a full-bleed
    poster, otherwise we fall back to the centred text-only business card.
    """
    width_mm, height_mm = size_mm
    card_w = max(1, int(width_mm * MM))
    card_h = max(1, int(height_mm * MM))
    corner_radius = int(CORNER_RADIUS_MM * MM)

    theme = _hex_to_rgb(spec.get("theme"), "#0B5FA8")
    accent = _hex_to_rgb(spec.get("accent"), "#F5A623")
    bg_style = (spec.get("bg_style") or "gradient").strip().lower()
    if bg_style == "solid":
        background = Image.new("RGB", (card_w, card_h), theme)
    else:
        darker = tuple(max(0, int(v * 0.55)) for v in theme)
        background = _vertical_gradient(card_w, card_h, theme, darker)

    # The plain gradient already carries the card; extra decoration rings
    # only read as stray marks on the finished card, so none are drawn.

    draw = ImageDraw.Draw(background)
    white = (255, 255, 255)
    soft = (235, 244, 255)

    slogan = (spec.get("slogan") or "").strip()
    name = (spec.get("name") or "").strip() or "姓名"
    title_text = (spec.get("title") or "").strip()
    unit_text = (spec.get("unit") or "").strip()
    line1 = " ".join(x for x in (title_text, unit_text) if x)
    contact = (spec.get("contact") or "").strip()
    note = (spec.get("note") or "").strip()

    # Text sizes follow the card height so a 16:9 card and a business card
    # both look deliberate.
    unit = card_h / 540.0

    if front_art is not None:
        # An AI-painted card face.  Keep the artwork readable: the scrim only
        # reaches for the footer so the type still has a calm base to sit on.
        background = _scrim(_cover(front_art, card_w, card_h, focus_y=0.5), theme, card_w, card_h, strength=1.25)
        draw = ImageDraw.Draw(background)

        pad_x = int(card_w * 0.055)
        pad_y = int(card_h * 0.075)
        name_size = int(84 * unit)
        info_size = int(30 * unit)
        contact_size = int(26 * unit)
        contact_line_h = int(38 * unit)

        contact_lines = [x.strip() for x in contact.splitlines() if x.strip()][:3]
        contact_block_h = len(contact_lines) * contact_line_h

        baseline = card_h - pad_y
        draw.text((pad_x, baseline - name_size), name, font=_font(max(20, name_size), bold=True), fill=white)

        if contact_lines:
            y = baseline - contact_block_h
            font = _font(max(11, contact_size), bold=False)
            for line in contact_lines:
                width = draw.textlength(line, font=font)
                draw.text((card_w - pad_x - width, y), line, font=font, fill=white)
                y += contact_line_h

        row_y = baseline - max(name_size, contact_block_h) - int(22 * unit)
        if line1:
            draw.text((pad_x, row_y), line1, font=_font(max(11, info_size), bold=False), fill=soft)
        if slogan:
            # The slogan is a quiet supporting line, not a second headline.
            font = _font(max(11, int(24 * unit)), bold=False)
            width = draw.textlength(slogan, font=font)
            draw.text((card_w - pad_x - width, row_y + int(6 * unit)), slogan, font=font, fill=soft)

        accent_y = row_y - int(28 * unit)
        draw.rounded_rectangle(
            (pad_x, accent_y, pad_x + int(96 * unit), accent_y + max(2, int(5 * unit))),
            radius=3,
            fill=accent,
        )

        if note:
            font = _font(max(10, int(22 * unit)), bold=False)
            draw.text((pad_x, baseline + int(12 * unit)), note, font=font, fill=soft)
    elif artwork is not None:
        # One full-bleed artwork with a single information bar at the bottom.
        # The previous layout cut the card in half (artwork left, text right)
        # and read as two unrelated pieces glued together.
        background = _scrim(_cover(artwork, card_w, card_h, focus_y=0.42), theme, card_w, card_h)
        draw = ImageDraw.Draw(background)

        pad_x = int(card_w * 0.055)
        pad_y = int(card_h * 0.075)
        name_size = int(76 * unit)
        info_size = int(28 * unit)
        contact_size = int(26 * unit)
        contact_line_h = int(36 * unit)

        contact_lines = [x.strip() for x in contact.splitlines() if x.strip()][:3]
        contact_block_h = len(contact_lines) * contact_line_h

        baseline = card_h - pad_y
        draw.text((pad_x, baseline - name_size), name, font=_font(max(20, name_size), bold=True), fill=white)

        if contact_lines:
            y = baseline - contact_block_h
            font = _font(max(11, contact_size), bold=False)
            for line in contact_lines:
                width = draw.textlength(line, font=font)
                draw.text((card_w - pad_x - width, y), line, font=font, fill=white)
                y += contact_line_h

        row_y = baseline - max(name_size, contact_block_h) - int(20 * unit)
        if line1:
            draw.text((pad_x, row_y), line1, font=_font(max(11, info_size), bold=False), fill=soft)
        if slogan:
            font = _font(max(11, info_size), bold=False)
            width = draw.textlength(slogan, font=font)
            draw.text((card_w - pad_x - width, row_y), slogan, font=font, fill=soft)

        accent_y = row_y - int(26 * unit)
        draw.rounded_rectangle(
            (pad_x, accent_y, pad_x + int(92 * unit), accent_y + max(2, int(5 * unit))),
            radius=3,
            fill=accent,
        )

        if note:
            font = _font(max(10, int(22 * unit)), bold=False)
            draw.text((pad_x, baseline + int(10 * unit)), note, font=font, fill=soft)
    else:
        if slogan:
            font = _font(max(12, int(26 * unit)), bold=False)
            w = draw.textlength(slogan, font=font)
            draw.text(((card_w - w) / 2, int(66 * unit)), slogan, font=font, fill=soft)

        font_name = _font(max(20, int(92 * unit)), bold=True)
        w = draw.textlength(name, font=font_name)
        draw.text(((card_w - w) / 2, int(168 * unit)), name, font=font_name, fill=white)

        if title_text:
            font = _font(max(12, int(36 * unit)), bold=False)
            w = draw.textlength(title_text, font=font)
            draw.text(((card_w - w) / 2, int(292 * unit)), title_text, font=font, fill=soft)
        if unit_text:
            font = _font(max(11, int(27 * unit)), bold=False)
            w = draw.textlength(unit_text, font=font)
            draw.text(((card_w - w) / 2, int(338 * unit)), unit_text, font=font, fill=soft)
        if title_text or unit_text:
            sep_w = int(220 * unit)
            draw.rounded_rectangle(((card_w - sep_w) / 2, int(392 * unit), (card_w + sep_w) / 2, int(392 * unit) + max(2, int(5 * unit))), radius=3, fill=accent)

        if contact:
            font = _font(max(11, int(30 * unit)), bold=False)
            y = int(432 * unit)
            for line in [x.strip() for x in contact.splitlines() if x.strip()][:3]:
                w = draw.textlength(line, font=font)
                draw.text(((card_w - w) / 2, y), line, font=font, fill=white)
                y += int(44 * unit)

        if note:
            font = _font(max(10, int(22 * unit)), bold=False)
            w = draw.textlength(note, font=font)
            draw.text(((card_w - w) / 2, card_h - int(52 * unit)), note, font=font, fill=soft)

    rounded = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    rounded.paste(background, (0, 0), _rounded_mask(card_w, card_h, corner_radius))
    return rounded.convert("RGB")


def render_back(template_path: str, spec: dict[str, Any], size_mm: tuple[float, float]) -> Image.Image:
    width_mm, height_mm = size_mm
    card_w = max(1, int(width_mm * MM))
    card_h = max(1, int(height_mm * MM))
    corner_radius = int(CORNER_RADIUS_MM * MM)
    unit = card_h / 540.0

    base = Image.open(template_path).convert("RGB")
    background = _cover(base, card_w, card_h)

    frame = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(frame)
    fdraw.rounded_rectangle(
        (int(14 * unit), int(14 * unit), card_w - int(14 * unit), card_h - int(14 * unit)),
        radius=max(2, corner_radius - 5),
        outline=(255, 255, 255, 220),
        width=max(2, int(4 * unit)),
    )
    caption = (spec.get("back_caption") or "").strip()
    if caption:
        font = _font(max(12, int(24 * unit)), bold=False)
        w = fdraw.textlength(caption, font=font)
        fdraw.text(((card_w - w) / 2, card_h - int(58 * unit)), caption, font=font, fill=(255, 255, 255, 235))
    background = Image.alpha_composite(background.convert("RGBA"), frame).convert("RGB")

    rounded = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    rounded.paste(background, (0, 0), _rounded_mask(card_w, card_h, corner_radius))
    return rounded.convert("RGB")


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
) -> str:
    """Cut file in millimetres. Layers:
      - outer cut (red, thin): the physical card outline
      - corner registration crosses (dashed thin)
      - inner engrave reference frame (green, thin)
      - artwork image layer (the visitor's model, embedded)
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

    data_uri = _embed_image_data_uri(artwork_path)
    if data_uri:
        panel_w = w * 0.46
        lines.append("  <!-- 作品图（可在此图层上雕刻/打印） -->")
        lines.append(
            f'<image x="1.2" y="1.2" width="{panel_w - 2.4:.2f}" height="{h - 2.4:.2f}" '
            f'preserveAspectRatio="xMidYMid slice" href="{data_uri}"/>'
        )

    theme = _hex_to_rgb(spec.get("theme"), "#0B5FA8")
    engrave = (engrave_text or "").strip() or (spec.get("name") or "").strip()
    if engrave:
        lines.append("  <!-- 姓名雕刻文字（蓝色，可在软件中转换为路径） -->")
        lines.append(
            f'<text x="{w / 2:.2f}" y="{h / 2:.2f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="Microsoft YaHei, SimHei, sans-serif" font-size="9" '
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
    back_template = (spec.get("back_template") or "activity_stage").strip()
    if not _TEMPLATE_SLUG_RE.match(back_template):
        back_template = "activity_stage"
    template_path = os.path.join(template_root, f"{back_template}.png")
    if not os.path.isfile(template_path):
        template_path = os.path.join(template_root, "activity_stage.png")
    if not os.path.isfile(template_path):
        template_path = os.path.join(template_root, "activity_blue.png")
    if not os.path.isfile(template_path):
        # Last resort: the templates that ship with the repository.
        template_path = os.path.join(str(PACKAGED_TEMPLATE_DIR), "activity_stage.png")
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

    # preview: side-by-side with labels
    label_h = 52
    preview = Image.new("RGB", (card_w * 2 + 60, card_h + label_h + 24), (240, 244, 248))
    pdraw = ImageDraw.Draw(preview)
    front_rgba = front.convert("RGBA")
    back_rgba = back.convert("RGBA")
    preview.paste(front_rgba, (30, label_h), front_rgba)
    preview.paste(back_rgba, (card_w + 60, label_h), back_rgba)
    label_font = _font(26, bold=True)
    pdraw.text((30, 10), "正面 · 你的作品", font=label_font, fill=(40, 80, 120))
    pdraw.text((card_w + 60, 10), "背面 · 活动背景", font=label_font, fill=(40, 80, 120))
    pdraw.rectangle((28, label_h - 2, card_w + 32, card_h + label_h + 2), outline=(120, 170, 200), width=2)
    pdraw.rectangle((card_w + 58, label_h - 2, card_w * 2 + 62, card_h + label_h + 2), outline=(120, 170, 200), width=2)
    png_path = os.path.join(out_dir, "card.png")
    preview.save(png_path)

    svg_path = os.path.join(out_dir, "card.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(build_svg(spec, size_mm, artwork_path=artwork_path))

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
        entry = registry.get(slug) or {}
        width_mm, height_mm = resolve_size_mm(slug, template_root)
        items.append({
            "id": slug,
            "name": entry.get("name") or TEMPLATE_NAMES.get(slug, slug),
            "url": f"/api/data/laser/template/{path.name}",
            "size_mm": {"width": width_mm, "height": height_mm},
            "generated": bool(entry),
            "side": entry.get("side") or "back",
        })
    return items
