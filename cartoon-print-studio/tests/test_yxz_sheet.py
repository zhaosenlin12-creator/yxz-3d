"""The pose-sheet detector must only fire on real contact sheets."""

import os
import sys

import pytest
from PIL import Image, ImageDraw

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import yxz_sheet  # noqa: E402


def _figure(draw, x, y, w, h, colour=(40, 60, 180)):
    draw.ellipse((x, y, x + w, y + h), fill=colour)


def _sheet(path):
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    for row in range(3):
        for col in range(3):
            _figure(draw, 20 + col * 195, 20 + row * 195, 150, 150)
    image.save(path)
    return path


def _single(path):
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    _figure(draw, 180, 60, 240, 480)
    image.save(path)
    return path


def _single_with_decorations(path):
    """One character with a halo and a few floating panels: still one design."""
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    _figure(draw, 200, 120, 200, 420)
    draw.ellipse((230, 30, 370, 80), outline=(40, 60, 180), width=12)
    for x, y in ((20, 60), (460, 120), (40, 430), (470, 420)):
        draw.rectangle((x, y, x + 70, y + 50), fill=(120, 190, 230))
    image.save(path)
    return path


def test_detects_a_pose_sheet(tmp_path):
    path = _sheet(str(tmp_path / "sheet.png"))
    box = yxz_sheet.find_subject_box(path)
    assert box is not None
    assert box[2] > box[0] and box[3] > box[1]


def test_leaves_a_single_design_alone(tmp_path):
    path = _single(str(tmp_path / "single.png"))
    assert yxz_sheet.find_subject_box(path) is None


def test_leaves_a_design_with_decorations_alone(tmp_path):
    path = _single_with_decorations(str(tmp_path / "decorated.png"))
    assert yxz_sheet.find_subject_box(path) is None


def test_the_crop_keeps_one_figure(tmp_path):
    src = _sheet(str(tmp_path / "sheet.png"))
    dst = str(tmp_path / "crop.png")
    assert yxz_sheet.crop_to_subject(src, dst) == dst
    with Image.open(dst) as cropped:
        assert cropped.width < 600 and cropped.height < 600


def test_a_missing_picture_is_not_a_sheet(tmp_path):
    assert yxz_sheet.find_subject_box(str(tmp_path / "nope.png")) is None
    assert yxz_sheet.crop_to_subject(
        str(tmp_path / "nope.png"), str(tmp_path / "out.png")) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
