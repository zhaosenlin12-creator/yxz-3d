# -*- coding: utf-8 -*-
"""Laser-cut business card generation for the 宜小智 laser workflow.

Design contract (fixed for cutting):
  - Card size: standard business card 85.6 x 54 mm, rendered at 10 px/mm
    => 856 x 540 px for PNG layers, SVG viewBox in millimetres.
  - Back side: a fixed template image (user-provided activity poster, e.g.
    activity_blue) is cover-fitted, rounded to 3 mm and given a 1 mm inner
    reference frame.  It is NOT user-editable in the normal flow.
  - Front side: user-edited fields (name/title/unit/contact/slogan/theme)
    rendered by this module.
  - SVG: outer cutting path (rounded rect rx=3 mm), 4 corner registration
    crosses, an inner engrave reference frame, optional engrave text layer
    and a safety note.  Unit is mm so xTool / LightBurn style software can
    open it directly.

Everything is deterministic and offline (PIL + SVG text), so the flow never
depends on a cloud image API.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

# 10 px/mm
MM = 10
CARD_W_MM = 85.6
CARD_H_MM = 54.0
CARD_W = int(CARD_W_MM * MM)  # 856
CARD_H = int(CARD_H_MM * MM)  # 540
CORNER_RADIUS_MM = 3.0
CORNER_RADIUS = int(CORNER_RADIUS_MM * MM)

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


def _cover(image: Image.Image, w: int, h: int) -> Image.Image:
    """Cover-fit the image into w x h and center it."""
    ratio = max(w / image.width, h / image.height)
    nw, nh = max(1, int(image.width * ratio)), max(1, int(image.height * ratio))
    resized = image.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def _vertical_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        img.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img.resize((w, h))


def render_front(spec: dict[str, Any]) -> Image.Image:
    theme = _hex_to_rgb(spec.get("theme"), "#0B5FA8")
    accent = _hex_to_rgb(spec.get("accent"), "#F5A623")
    bg_style = (spec.get("bg_style") or "gradient").strip().lower()
    if bg_style == "solid":
        background = Image.new("RGB", (CARD_W, CARD_H), theme)
    else:
        darker = tuple(max(0, int(v * 0.55)) for v in theme)
        background = _vertical_gradient(CARD_W, CARD_H, theme, darker)

    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # decorative circle top-left + big arc bottom-right
    odraw.ellipse((28, 28, 118, 118), fill=(*accent, 110))
    odraw.ellipse((CARD_W - 190, CARD_H - 190, CARD_W - 30, CARD_H - 30), outline=(*accent, 70), width=4)
    background = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(background)
    white = (255, 255, 255)
    soft = (235, 244, 255)
    accent_text = accent

    slogan = (spec.get("slogan") or "").strip()
    if slogan:
        font = _font(26, bold=False)
        w = draw.textlength(slogan, font=font)
        draw.text(((CARD_W - w) / 2, 66), slogan, font=font, fill=soft)

    name = (spec.get("name") or "").strip() or "姓名"
    font_name = _font(92, bold=True)
    w = draw.textlength(name, font=font_name)
    draw.text(((CARD_W - w) / 2, 168), name, font=font_name, fill=white)

    line1 = " ".join(x.strip() for x in [(spec.get("title") or "").strip(), (spec.get("unit") or "").strip()] if x)
    if line1:
        font = _font(36, bold=False)
        w = draw.textlength(line1, font=font)
        draw.text(((CARD_W - w) / 2, 292), line1, font=font, fill=soft)
        # accent separator
        sy = 360
        sep_w = 220
        draw.rounded_rectangle(((CARD_W - sep_w) / 2, sy, (CARD_W + sep_w) / 2, sy + 5), radius=3, fill=accent_text)

    contact = (spec.get("contact") or "").strip()
    if contact:
        font = _font(30, bold=False)
        lines = [line.strip() for line in contact.splitlines() if line.strip()]
        y = 400
        for line in lines[:3]:
            w = draw.textlength(line, font=font)
            draw.text(((CARD_W - w) / 2, y), line, font=font, fill=white)
            y += 44

    note = (spec.get("note") or "").strip()
    if note:
        font = _font(22, bold=False)
        w = draw.textlength(note, font=font)
        draw.text(((CARD_W - w) / 2, CARD_H - 52), note, font=font, fill=soft)

    # rounded corners
    rounded = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    rounded.paste(background, (0, 0), _rounded_mask(CARD_W, CARD_H, CORNER_RADIUS))
    return rounded.convert("RGB")


def render_back(template_path: str, spec: dict[str, Any]) -> Image.Image:
    base = Image.open(template_path).convert("RGB")
    background = _cover(base, CARD_W, CARD_H)

    # white inner frame (reference for cutting placement)
    frame = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(frame)
    fdraw.rounded_rectangle(
        (14, 14, CARD_W - 14, CARD_H - 14),
        radius=CORNER_RADIUS - 5,
        outline=(255, 255, 255, 220),
        width=4,
    )
    caption = (spec.get("back_caption") or "").strip()
    if caption:
        font = _font(24, bold=False)
        w = fdraw.textlength(caption, font=font)
        fdraw.text(((CARD_W - w) / 2, CARD_H - 58), caption, font=font, fill=(255, 255, 255, 235))
    background = Image.alpha_composite(background.convert("RGBA"), frame).convert("RGB")

    rounded = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    rounded.paste(background, (0, 0), _rounded_mask(CARD_W, CARD_H, CORNER_RADIUS))
    return rounded.convert("RGB")


def _svg_rounded_rect(x: float, y: float, w: float, h: float, r: float, fill: str, stroke: str, stroke_width: float) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
    )


def build_svg(spec: dict[str, Any], engrave_text: str = "") -> str:
    """Cut file in millimetres. Layers:
      - outer cut (red, thin): the physical card outline
      - corner registration crosses (dashed thin)
      - inner engrave reference frame (green, thin)
      - optional engrave text (blue, converted to paths is left to the tool)
    """
    x, y, w, h = 0.0, 0.0, CARD_W_MM, CARD_H_MM
    r = CORNER_RADIUS_MM
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="85.6mm" height="54mm" viewBox="0 0 85.6 54">',
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
        f'fill="#888888">85.6 × 54 mm · 0.2–3 mm 板材请按实际校准</text>'
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
) -> dict[str, str]:
    """Render front/back/preview PNGs and the cut SVG under
    data_root/laser/<sid>/. Returns absolute paths."""
    data_root = os.path.abspath(data_root)
    template_root = template_root or os.path.join(data_root, "laser", "template")
    back_template = (spec.get("back_template") or "activity_blue").strip()
    if not _TEMPLATE_SLUG_RE.match(back_template):
        back_template = "activity_blue"
    template_path = os.path.join(template_root, f"{back_template}.png")
    if not os.path.isfile(template_path):
        template_path = os.path.join(template_root, "activity_blue.png")
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"名片背面模板缺失：{template_path}")

    sid = _safe_slug(str(spec.get("session_id") or uuid.uuid4().hex[:12]), uuid.uuid4().hex[:12])
    out_dir = os.path.join(data_root, "laser", sid)
    os.makedirs(out_dir, exist_ok=True)

    front = render_front(spec)
    back = render_back(template_path, spec)
    front_path = os.path.join(out_dir, "card_front.png")
    back_path = os.path.join(out_dir, "card_back.png")
    front.save(front_path)
    back.save(back_path)

    # preview: side-by-side with labels
    preview = Image.new("RGB", (CARD_W * 2 + 60, CARD_H + 44), (240, 244, 248))
    pdraw = ImageDraw.Draw(preview)
    front_rgba = front.convert("RGBA")
    back_rgba = back.convert("RGBA")
    preview.paste(front_rgba, (30, 30), front_rgba)
    preview.paste(back_rgba, (CARD_W + 60, 30), back_rgba)
    label_font = _font(26, bold=True)
    pdraw.text((30, 8), "正面 · 用户编辑", font=label_font, fill=(40, 80, 120))
    pdraw.text((CARD_W + 60, 8), "背面 · 固定模板", font=label_font, fill=(40, 80, 120))
    pdraw.rectangle((28, 28, CARD_W + 32, CARD_H + 32), outline=(120, 170, 200), width=2)
    pdraw.rectangle((CARD_W + 58, 28, CARD_W * 2 + 62, CARD_H + 32), outline=(120, 170, 200), width=2)
    png_path = os.path.join(out_dir, "card.png")
    preview.save(png_path)

    svg_path = os.path.join(out_dir, "card.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(build_svg(spec))

    return {
        "session_id": sid,
        "svg_path": svg_path,
        "png_path": png_path,
        "front_path": front_path,
        "back_path": back_path,
        "back_template": back_template,
        "size_mm": {"width": CARD_W_MM, "height": CARD_H_MM},
    }


def list_templates(template_root: str) -> list[dict[str, str]]:
    root = Path(template_root)
    items: list[dict[str, str]] = []
    if not root.is_dir():
        return items
    for path in sorted(root.glob("*.png")):
        slug = path.stem
        if _TEMPLATE_SLUG_RE.match(slug):
            items.append({"id": slug, "name": slug, "url": f"/api/data/laser/template/{path.name}"})
    return items
