# -*- coding: utf-8 -*-
"""Compose the 宜小智 app icons from the character layers.

The character is drawn in layers (body / eyes / mouth / glow) so that the
stage can move the eyes around.  An icon needs the same picture, but
flat: the helmet, the halo and a smile.  This script paints exactly the
same layers on top of each other and writes the icon files the web app
and the browser tab expect.

Run it with the backend interpreter (it needs Pillow):

    cartoon-print-studio\\ai\\forge-webui\\venv\\Scripts\\python.exe \
        cartoon-print-studio\\scripts\\make_yxz_icons.py
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent.parent
LAYERS = ROOT / "airi" / "packages" / "stage-ui" / "src" / "assets" / "yxz" / "layers"
PUBLIC = ROOT / "airi" / "apps" / "stage-web" / "public"

# The colours of the app: a deep 宜昌 blue the white robot reads well on.
TOP_COLOR = (11, 74, 122)
BOTTOM_COLOR = (24, 168, 224)

# The part of the artwork that carries the character: helmet, halo, face.
HEAD_BOX = (140, 0, 960, 800)


def vertical_gradient(width: int, height: int) -> Image.Image:
    """The blue backdrop every icon sits on."""
    column = Image.new("RGB", (1, height))
    pixels = column.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels[0, y] = tuple(
            int(round(TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * t))
            for i in range(3)
        )
    return column.resize((width, height), Image.BILINEAR)


def compose_character() -> Image.Image:
    """Paint the character exactly the way the stage does."""
    manifest = json.loads((LAYERS / "manifest.json").read_text(encoding="utf-8"))
    width = int(manifest["width"])
    height = int(manifest["height"])

    body = Image.open(LAYERS / "body.png").convert("RGBA")
    art = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    art.alpha_composite(body, (0, 0))

    # The halo is welded into the body layer, but the light it throws is
    # still a separate piece laid over the picture.
    glow_box = manifest["layers"]["glow"]
    glow = Image.open(LAYERS / glow_box["file"]).convert("RGBA")
    lit = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    lit.alpha_composite(glow, (int(glow_box["x"]), int(glow_box["y"])))
    art = Image.alpha_composite(art, lit)

    for eye in manifest["layers"]["eyes"]:
        image = Image.open(LAYERS / eye["file"]).convert("RGBA")
        left = int(round(eye["cx"] - eye["w"] / 2))
        top = int(round(eye["cy"] - eye["h"] / 2))
        art.alpha_composite(image, (left, top))

    mouth = manifest["layers"]["mouths"][0]
    image = Image.open(LAYERS / mouth["file"]).convert("RGBA")
    left = int(round(mouth["cx"] - mouth["w"] / 2))
    top = int(round(mouth["cy"] - mouth["h"] / 2))
    art.alpha_composite(image, (left, top))
    return art


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def head_art(scale_to: int) -> Image.Image:
    """The cropped head, scaled so its width is ``scale_to`` pixels."""
    art = compose_character().crop(HEAD_BOX)
    scale = scale_to / art.width
    return art.resize((scale_to, max(1, int(art.height * scale))), Image.LANCZOS)


def build_icon(size: int, *, padding: float = 0.07) -> Image.Image:
    """Paint one rounded-square icon."""
    canvas = vertical_gradient(size, size).convert("RGBA")

    # A soft light behind the head, so the white helmet does not vanish
    # into the white parts of the picture.
    halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (size * 0.06, size * 0.0, size * 0.94, size * 0.76),
        fill=(120, 220, 255, 70),
    )
    halo = halo.filter(ImageFilter.GaussianBlur(size * 0.09))
    canvas = Image.alpha_composite(canvas, halo)

    head = head_art(int(size * (1 - padding * 2)))
    canvas.alpha_composite(head, ((size - head.width) // 2, int(size * 0.05)))
    canvas.putalpha(rounded_mask(size, int(size * 0.22)))
    return canvas.convert("RGB")


def build_maskable(size: int) -> Image.Image:
    """The icon the system may crop into any shape: the picture has to sit
    well inside the safe zone and the background has to reach the edges."""
    canvas = vertical_gradient(size, size).convert("RGBA")
    head = head_art(int(size * 0.6))
    canvas.alpha_composite(head, ((size - head.width) // 2, int(size * 0.16)))
    return canvas.convert("RGB")


def save_png(image: Image.Image, path: Path) -> None:
    image.save(path, format="PNG", optimize=True)
    print("  %s  %.0f KB" % (path.relative_to(ROOT), path.stat().st_size / 1024))


def write_svg_favicon(master: Image.Image) -> None:
    """The SVG favicon is the composed picture on a rounded square, with
    the bitmap embedded so the browser never fetches anything."""
    buffer = io.BytesIO()
    # A smaller picture keeps the file light: the browser tab never shows
    # the icon bigger than 64 pixels anyway.
    master.resize((192, 192), Image.LANCZOS).save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">',
        '  <defs><clipPath id="yxz"><rect width="512" height="512" rx="113" ry="113"/></clipPath></defs>',
        '  <g clip-path="url(#yxz)">',
        '    <image width="512" height="512" href="data:image/png;base64,%s"/>' % encoded,
        '  </g>',
        '</svg>',
        '',
    ]
    path = PUBLIC / "favicon.svg"
    path.write_text("\n".join(parts), encoding="utf-8")
    print("  %s  %.0f KB" % (path.relative_to(ROOT), path.stat().st_size / 1024))


def write_open_graph() -> None:
    """The share picture: the character on the left, the name on the right."""
    width, height = 1280, 640
    og = vertical_gradient(width, height).convert("RGBA")
    head = head_art(int(height * 0.56))
    og.alpha_composite(head, (int(height * 0.06), (height - head.height) // 2))

    draw = ImageDraw.Draw(og)
    try:
        from PIL import ImageFont

        title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 132)
        subtitle = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 44)
    except Exception:
        title = ImageFont.load_default()
        subtitle = ImageFont.load_default()
    draw.text((int(height * 0.70), int(height * 0.26)), "宜小智", font=title, fill=(255, 255, 255, 255))
    draw.text(
        (int(height * 0.72), int(height * 0.56)),
        "AI 智能创造 · 3D 打印 · 激光切割",
        font=subtitle,
        fill=(214, 240, 255, 255),
    )
    save_png(og.convert("RGB"), PUBLIC / "open-graph.png")


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    master = build_icon(512)
    print("icons:")
    save_png(master, PUBLIC / "web-app-manifest-512x512.png")
    save_png(build_icon(192), PUBLIC / "web-app-manifest-192x192.png")
    save_png(build_icon(180), PUBLIC / "apple-touch-icon.png")
    save_png(build_maskable(192), PUBLIC / "maskable_icon_x192.png")
    save_png(build_maskable(512), PUBLIC / "maskable_icon_x512.png")

    # The browser tab icon: several sizes inside one .ico file.
    master.save(
        PUBLIC / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)],
    )
    print("  favicon.ico  %.0f KB" % ((PUBLIC / "favicon.ico").stat().st_size / 1024))

    write_svg_favicon(master)
    write_open_graph()
    print("done")


if __name__ == "__main__":
    main()
