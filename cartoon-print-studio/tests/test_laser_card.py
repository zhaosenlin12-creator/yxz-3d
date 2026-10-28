import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import laser_card


class LaserCardTests(unittest.TestCase):
    """The card is the physical end of the chain, so its faces are checked
    pixel by pixel: the back owns a big activity title, the front carries the
    visitor's own artwork above a solid information bar, and the preview
    stacks the two faces instead of shrinking them side by side."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.template_root = laser_card.ensure_templates(str(self.root))
        self.spec = {
            "name": "张一鸣",
            "title": "初中生",
            "unit": "宜昌市实验中学",
            "contact": "13800000000\n微信 zhangym",
            "slogan": "数理创未来 智慧启新程",
            "theme": "#0B5FA8",
            "accent": "#F5A623",
            "back_template": "activity_yichang",
        }

    def make_artwork(self):
        path = self.root / "artwork.png"
        Image.new("RGB", (1024, 1024), (220, 40, 60)).save(path)
        return str(path)

    def generate(self, **extra):
        spec = dict(self.spec)
        spec.update(extra)
        return laser_card.generate(spec, str(self.root), self.template_root)

    def test_card_uses_the_rectangular_activity_size(self):
        result = self.generate()
        self.assertEqual(result["size_mm"], {"width": 100.0, "height": 56.25})
        self.assertEqual(result["back_template"], "activity_yichang")

    def test_back_carries_the_activity_theme_in_big_type(self):
        result = self.generate()
        back = Image.open(result["back_path"]).convert("RGB")
        width, height = back.size

        # The title band is the middle of the face.  Typeset white text on a
        # dark template makes it far brighter than the same band of the raw
        # artwork, which is what makes the theme read from a metre away.
        raw = Image.open(
            Path(self.template_root) / "activity_yichang.png"
        ).convert("RGB").resize((width, height))

        def brightness(image):
            band = image.crop((0, int(height * 0.18), width, int(height * 0.48)))
            pixels = band.convert("L").getdata()
            return sum(pixels) / len(pixels)

        self.assertGreater(brightness(back), brightness(raw) + 12)

    def test_front_puts_the_artwork_above_a_solid_information_bar(self):
        result = self.generate(artwork_path=self.make_artwork())
        self.assertTrue(result["has_artwork"])
        front = Image.open(result["front_path"]).convert("RGB")
        width, height = front.size

        # The picture area keeps the artwork, the bar underneath is the theme
        # colour instead of the artwork.
        artwork_pixel = front.getpixel((width // 2, int(height * 0.10)))
        bar_pixel = front.getpixel((int(width * 0.90), int(height * 0.95)))
        self.assertGreater(artwork_pixel[0], 180)
        self.assertLess(artwork_pixel[2], 100)
        self.assertLess(bar_pixel[0], 120)
        self.assertGreater(bar_pixel[2], bar_pixel[0])

    def test_preview_stacks_the_front_above_the_back(self):
        result = self.generate(artwork_path=self.make_artwork())
        preview = Image.open(result["png_path"])
        width, height = preview.size
        # One card is 16:9; stacked with labels the sheet is clearly taller
        # than it is wide, which is what "one glance" needs.
        self.assertGreater(height, width)

    def test_cut_file_carries_both_faces(self):
        result = self.generate(artwork_path=self.make_artwork())
        svg = Path(result["svg_path"]).read_text(encoding="utf-8")
        self.assertIn("正面作品图", svg)
        self.assertIn("背面活动主视觉", svg)
        self.assertIn('width="100.0mm"', svg)
        self.assertIn('height="56.25mm"', svg)

    def test_template_preview_renders_the_themed_back(self):
        payload = laser_card.render_template_preview(
            self.template_root,
            "activity_yichang",
            title=laser_card.DEFAULT_BACK_TITLE,
            subtitle=laser_card.DEFAULT_BACK_SUBTITLE,
        )
        self.assertTrue(payload)
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
