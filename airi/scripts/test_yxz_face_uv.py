import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yxz_face_uv import interpolate_uv


class InterpolateUvTests(unittest.TestCase):
    def test_interpolates_texture_coordinates_at_triangle_interior(self):
        result = interpolate_uv(
            (0.25, 0.25, 0.0),
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ),
            (
                (0.1, 0.2),
                (0.9, 0.2),
                (0.1, 0.8),
            ),
        )

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.3)
        self.assertAlmostEqual(result[1], 0.35)

    def test_returns_none_for_degenerate_triangle(self):
        result = interpolate_uv(
            (0.5, 0.0, 0.0),
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
            ),
            (
                (0.0, 0.0),
                (0.5, 0.0),
                (1.0, 0.0),
            ),
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
