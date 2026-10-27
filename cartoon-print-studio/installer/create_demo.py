"""Create a small, synthetic offline demo without copying user artwork."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent / "demo"
MODEL = ROOT / "model"
PREVIEWS = ROOT / "previews"


def sphere(center, scale, color):
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1)
    mesh.apply_scale(scale)
    mesh.apply_translation(center)
    mesh.visual.vertex_colors = np.tile(np.asarray([*color, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    return mesh


def make_model():
    parts = [
        sphere((0, 0, 27), (14, 10, 22), (52, 133, 221)),
        sphere((0, 0, 53), (16, 13, 15), (75, 163, 239)),
        sphere((-10, -1, 65), (5, 4, 9), (74, 150, 229)),
        sphere((10, -1, 65), (5, 4, 9), (74, 150, 229)),
        sphere((0, -1, 54), (17, 14, 17), (211, 239, 255)),
        sphere((0, -14, 53), (13, 3, 12), (66, 133, 201)),
        sphere((-7, -16, 56), (1.5, 1, 1.5), (20, 42, 67)),
        sphere((7, -16, 56), (1.5, 1, 1.5), (20, 42, 67)),
        sphere((0, -16.5, 49), (2.3, 1, 1.5), (246, 117, 124)),
        sphere((-10, 0, 29), (7, 11, 15), (242, 139, 72)),
        sphere((10, 0, 29), (7, 11, 15), (242, 139, 72)),
        sphere((0, 0, 5), (13, 10, 5), (250, 177, 94)),
    ]
    ROOT.mkdir(parents=True, exist_ok=True)
    MODEL.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    model = trimesh.util.concatenate(parts)
    model.export(MODEL / "mesh.glb")
    model.export(MODEL / "mesh.stl")
    model.export(MODEL / "mesh.obj")
    return model


def make_preview():
    image = Image.new("RGB", (768, 768), (244, 248, 251))
    draw = ImageDraw.Draw(image)
    draw.ellipse((194, 678, 574, 730), fill=(221, 229, 236))
    draw.ellipse((282, 338, 486, 659), fill=(52, 126, 215))
    draw.ellipse((251, 165, 517, 456), fill=(208, 233, 250), outline=(109, 160, 204), width=9)
    draw.ellipse((270, 183, 498, 429), fill=(74, 151, 224), outline=(224, 243, 255), width=12)
    draw.polygon([(302, 213), (287, 119), (361, 180)], fill=(78, 148, 220))
    draw.polygon([(429, 181), (501, 117), (487, 219)], fill=(78, 148, 220))
    draw.ellipse((346, 270, 359, 283), fill=(25, 47, 68))
    draw.ellipse((410, 270, 423, 283), fill=(25, 47, 68))
    draw.arc((365, 286, 405, 319), 10, 170, fill=(248, 149, 158), width=6)
    draw.polygon([(312, 383), (457, 383), (476, 588), (384, 638), (292, 588)], fill=(241, 135, 66))
    draw.rounded_rectangle((287, 326, 481, 666), radius=80, fill=(58, 133, 222))
    draw.ellipse((344, 431, 424, 513), fill=(246, 186, 82), outline=(255, 226, 159), width=8)
    image.save(PREVIEWS / "img_0.png", optimize=True)


if __name__ == "__main__":
    make_model()
    make_preview()
    (ROOT / "demo.json").write_text(
        json.dumps({"prompt": "一只戴宇航员头盔的卡通猫咪"}, ensure_ascii=False),
        encoding="utf-8",
    )
