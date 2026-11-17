"""Zero-key preview renderer.

Cloud image providers can run out of credits (MiniMax token plan, AIXJ, JOJO)
and the packaged desktop build intentionally does not ship torch/SD.  Instead
of showing "预览失败", draw a clean, on-theme design board locally so the
conversation can continue into the workbench.  These are labelled as local
concept drafts, not photoreal model photos.
"""
from __future__ import annotations

import io
import math
import os
import re
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = H = 1024
S = 2  # supersample


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _bg(accent: Tuple[int, int, int]) -> Image.Image:
    """Soft vertical gradient with a large off-centre halo."""
    top = (248, 252, 255)
    bottom = (226, 240, 251)
    base = Image.new("RGB", (W * S, H * S), top)
    d = ImageDraw.Draw(base)
    for y in range(H * S):
        t = y / (H * S)
        d.line(
            [(0, y), (W * S, y)],
            fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            ),
        )
    halo = Image.new("RGB", (W * S, H * S), (0, 0, 0))
    hd = ImageDraw.Draw(halo)
    cx, cy, r = int(W * S * 0.5), int(H * S * 0.42), int(W * S * 0.34)
    hd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    halo = halo.filter(ImageFilter.GaussianBlur(int(W * S * 0.13)))
    base = Image.blend(base, Image.blend(base, halo, 0.28), 0.55)
    return base


def _gear(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, accent, teeth: int = 20):
    # Glow ring
    draw.ellipse([cx - r * 1.13, cy - r * 1.13, cx + r * 1.13, cy + r * 1.13],
                 outline=accent + (110,), width=int(r * 0.045))
    # Teeth: four clean trapezoid points per tooth, no star-shaped spikes.
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        p = [
            (cx + math.cos(a - .10) * r, cy + math.sin(a - .10) * r),
            (cx + math.cos(a - .055) * r * 1.16, cy + math.sin(a - .055) * r * 1.16),
            (cx + math.cos(a + .055) * r * 1.16, cy + math.sin(a + .055) * r * 1.16),
            (cx + math.cos(a + .10) * r, cy + math.sin(a + .10) * r),
        ]
        draw.polygon(p, fill=accent + (255,))
    # Body discs
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(64, 145, 196, 255))
    draw.ellipse([cx - r * .9, cy - r * .9, cx + r * .9, cy + r * .9], fill=(158, 216, 244, 255))
    draw.ellipse([cx - r * .78, cy - r * .78, cx + r * .78, cy + r * .78], fill=(245, 251, 255, 255))
    # Hub
    draw.ellipse([cx - r * .34, cy - r * .34, cx + r * .34, cy + r * .34], fill=(42, 117, 166, 255))
    draw.ellipse([cx - r * .24, cy - r * .24, cx + r * .24, cy + r * .24], outline=accent + (255,), width=int(r * .035))
    # Spokes
    for i in range(8):
        a = 2 * math.pi * i / 8 + .2
        draw.line(
            [(cx + math.cos(a) * r * .3, cy + math.sin(a) * r * .3),
             (cx + math.cos(a) * r * .7, cy + math.sin(a) * r * .7)],
            fill=(76, 158, 205, 210), width=int(r * .045),
        )


def _robot(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, accent):
    w, h = r * 1.5, r * 1.05
    # ears
    draw.rounded_rectangle([cx - w * .62, cy - h * .18, cx - w * .46, cy + h * .18],
                           radius=int(r * .06), fill=(72, 150, 198, 255))
    draw.rounded_rectangle([cx + w * .46, cy - h * .18, cx + w * .62, cy + h * .18],
                           radius=int(r * .06), fill=(72, 150, 198, 255))
    # head
    draw.rounded_rectangle([cx - w * .5, cy - h * .58, cx + w * .5, cy + h * .5],
                           radius=int(r * .26), fill=(252, 254, 255, 255))
    # visor
    draw.rounded_rectangle([cx - w * .36, cy - h * .34, cx + w * .36, cy + h * .12],
                           radius=int(r * .18), fill=(24, 51, 84, 255))
    # eyes
    for dx in (-1, 1):
        draw.ellipse([cx + dx * r * .2 - r * .11, cy - r * .16 - r * .08,
                      cx + dx * r * .2 + r * .11, cy - r * .16 + r * .08],
                     fill=accent + (255,))
    # mouth
    draw.arc([cx - r * .18, cy + r * .02, cx + r * .18, cy + r * .22], 15, 165,
             fill=(120, 200, 240, 255), width=int(r * .05))
    # antenna + body
    draw.line([(cx, cy - h * .58), (cx, cy - h * .78)], fill=(80, 160, 205, 255), width=int(r * .04))
    draw.ellipse([cx - r * .07, cy - h * .87, cx + r * .07, cy - h * .73], fill=accent + (255,))
    draw.rounded_rectangle([cx - w * .3, cy + h * .42, cx + w * .3, cy + h * .92],
                           radius=int(r * .12), fill=(238, 248, 254, 255))


def _system(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, accent):
    draw.ellipse([cx - r * .26, cy - r * .26, cx + r * .26, cy + r * .26], fill=(255, 209, 92, 255))
    for i, rr in enumerate((.55, .78, 1.0)):
        draw.ellipse([cx - r * rr, cy - r * rr * .55, cx + r * rr, cy + r * rr * .55],
                     outline=(120, 190, 225, 160), width=int(r * .025))
        a = 0.8 + i * 1.9
        px, py = cx + math.cos(a) * r * rr, cy + math.sin(a) * r * rr * .55
        pr = r * (.055 + .015 * i)
        draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=accent + (255,))


def _badge(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, accent):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(28, 92, 138, 255))
    draw.ellipse([cx - r * .9, cy - r * .9, cx + r * .9, cy + r * .9], fill=(233, 246, 253, 255))
    _gear(draw, cx, cy, r * .6, accent, teeth=16)


def _default(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, accent):
    draw.rounded_rectangle([cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55],
                           radius=int(r * .22), fill=(235, 248, 255, 255))
    draw.ellipse([cx - r * .3, cy - r * .3, cx + r * .3, cy + r * .3], fill=accent + (255,))


def _pick(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("齿轮", "gear", "徽章", "badge", "奖牌", "logo")):
        return "gear"
    if any(k in p for k in ("机器人", "robot", "宇航", "太空服", "机甲")):
        return "robot"
    if any(k in p for k in ("太阳系", "planet", "行星", "宇宙", "星空")):
        return "system"
    return "default"


def _short_title(prompt: str) -> str:
    t = re.sub(r"[，。,.、；;：:\n].*$", "", prompt.strip())
    return (t or "我的设计")[:16]


def render_previews(prompt: str, out_dir: str, n: int = 4) -> Tuple[str, List[Tuple[bytes, str]]]:
    os.makedirs(out_dir, exist_ok=True)
    kind = _pick(prompt)
    accents = [(64, 181, 232), (92, 158, 230), (66, 205, 181), (238, 152, 96)]
    results: List[Tuple[bytes, str]] = []
    title = _short_title(prompt)
    for i in range(max(1, n)):
        accent = accents[i % len(accents)]
        im = _bg(accent).convert("RGBA")
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = W * S * .5, H * S * .43
        r = W * S * .24
        fn = {"gear": _gear, "robot": _robot, "system": _system, "badge": _badge}.get(kind, _default)
        if kind == "gear":
            _badge(d, cx, cy, r, accent)
        else:
            fn(d, cx, cy, r, accent)
        # ground shadow
        d.ellipse([cx - r * 1.1, cy + r * .95, cx + r * 1.1, cy + r * 1.18],
                  fill=(40, 86, 116, 38))
        im = Image.alpha_composite(im, layer)
        draw = ImageDraw.Draw(im)

        # corner label + scale
        f_tag = _font(38 * S)
        draw.rounded_rectangle([W * S * .06, H * S * .07, W * S * .27, H * S * .13],
                               radius=22 * S, fill=(255, 255, 255, 230))
        draw.text((W * S * .10, H * S * .083), f"草案 {i + 1:02d}", font=f_tag, fill=(42, 98, 135))
        draw.text((W * S * .06, H * S * .16), "LOCAL DESIGN PREVIEW", font=_font(22 * S),
                  fill=(96, 145, 174))
        draw.text((W * S * .06, H * S * .93), "本地概念稿 · 进入工作台继续 3D / STL",
                  font=_font(26 * S), fill=(104, 148, 176))

        im = im.convert("RGB").resize((W, H), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        results.append((buf.getvalue(), "local-design"))
    return "local-design", results
