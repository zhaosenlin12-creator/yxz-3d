import os
import sys
import tempfile
import unittest
from pathlib import Path


WORKTREE = Path(__file__).resolve().parents[1]
os.environ.setdefault("CARTOON_ROOT", str(WORKTREE))
sys.path.insert(0, str(WORKTREE / "backend"))

import numpy as np
import trimesh
from PIL import Image

import mesh_postprocess


class CartoonReliefPrintabilityTests(unittest.TestCase):
    """The relief is the default printable output, so it must slice cleanly."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="cartoon-relief-tests-")
        cls.output = Path(cls._tmp.name)
        source = cls.output / "source.png"
        canvas = np.zeros((160, 160, 4), dtype=np.uint8)
        canvas[30:130, 40:120] = (40, 120, 210, 255)
        canvas[50:80, 60:100] = (250, 240, 200, 255)
        Image.fromarray(canvas, "RGBA").save(source)
        mesh_postprocess.cartoon_3d_figurine(
            str(source), str(cls.output), target_side=128, base_disk_mm=2.5,
        )
        cls.mesh = trimesh.load(cls.output / "mesh.stl", force="mesh")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_relief_is_watertight_and_has_valid_volume(self):
        self.assertTrue(self.mesh.is_watertight, "relief must be watertight for slicing")
        self.assertTrue(self.mesh.is_volume, "relief must enclose a valid volume")
        self.assertGreater(float(self.mesh.volume), 0.0)

    def test_relief_has_no_degenerate_faces(self):
        self.assertTrue(self.mesh.nondegenerate_faces().all())
        self.assertTrue((np.asarray(self.mesh.area_faces) > 0).all())

    def test_relief_keeps_body_and_base_as_two_solid_parts(self):
        parts = self.mesh.split(only_watertight=False)
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertTrue(part.is_watertight)
            self.assertTrue(part.is_volume)

    def test_relief_export_keeps_vertex_colours(self):
        glb = trimesh.load(self.output / "mesh.glb", force="mesh")
        colours = np.asarray(glb.visual.vertex_colors)
        self.assertEqual(len(colours), len(glb.vertices))
        self.assertGreater(len(np.unique(colours[:, :3], axis=0)), 1)

    def test_sanitize_drops_collapsed_triangles(self):
        vertices = np.array([
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0], [2.0, 0.0, 0.0],
        ])
        faces = np.array([
            [0, 1, 2], [1, 3, 2], [1, 4, 1], [2, 3, 4],
        ])
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        original_faces = len(mesh.faces)
        cleaned = mesh_postprocess._sanitize_printable_mesh(mesh)
        self.assertLess(len(cleaned.faces), original_faces)
        self.assertTrue(cleaned.nondegenerate_faces().all())


if __name__ == "__main__":
    unittest.main()
