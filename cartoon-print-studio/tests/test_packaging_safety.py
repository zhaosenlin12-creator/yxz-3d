import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKTREE = Path(__file__).resolve().parents[1]


class InstallerSafetyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_install_and_upgrade_preserve_device_data_and_credentials(self):
        with tempfile.TemporaryDirectory(prefix="cartoon-installer-test-") as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            install = root / "installed"
            (bundle / "_internal").mkdir(parents=True)
            (bundle / "data" / "demo" / "model").mkdir(parents=True)
            (bundle / "data" / "demo" / "previews").mkdir(parents=True)
            (bundle / "CartoonPrintStudio.exe").write_bytes(b"app-v1")
            (bundle / "_internal" / "runtime.dat").write_bytes(b"runtime-v1")
            (bundle / "data" / "demo" / "model" / "mesh.glb").write_bytes(b"demo-v1")
            (bundle / "data" / "demo" / "previews" / "img_0.png").write_bytes(b"preview-v1")

            def install_bundle():
                return subprocess.run(
                    [
                        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        f"& '{WORKTREE / 'installer' / 'install.ps1'}' -InstallDir '{install}' "
                        f"-BundleDir '{bundle}' -CreateShortcut:$false",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            first = install_bundle()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((install / "data" / "demo" / "model" / "mesh.glb").is_file())
            self.assertTrue((install / "keys.txt").is_file())
            self.assertFalse((install / "keys.txt").read_bytes().startswith(b"app"))

            projects = install / "data" / "projects" / "customer.json"
            projects.parent.mkdir(parents=True)
            projects.write_text('{"name":"local project"}', encoding="utf-8")
            keys = install / "keys.txt"
            keys.write_text("TRIPO:3D\ncustomer-key", encoding="utf-8")
            local_file = install / "keep-me.txt"
            local_file.write_text("local", encoding="utf-8")
            (bundle / "CartoonPrintStudio.exe").write_bytes(b"app-v2")
            (bundle / "data" / "demo" / "model" / "mesh.glb").write_bytes(b"demo-v2")

            upgraded = install_bundle()
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
            self.assertEqual((install / "CartoonPrintStudio.exe").read_bytes(), b"app-v2")
            self.assertEqual(projects.read_text(encoding="utf-8"), '{"name":"local project"}')
            self.assertEqual(keys.read_text(encoding="utf-8"), "TRIPO:3D\ncustomer-key")
            self.assertEqual(local_file.read_text(encoding="utf-8"), "local")
            self.assertEqual(
                (install / "data" / "demo" / "model" / "mesh.glb").read_bytes(), b"demo-v1"
            )

    def test_generated_demo_contains_no_user_artwork_and_valid_mesh_files(self):
        import sys
        import trimesh
        from PIL import Image

        sys.path.insert(0, str(WORKTREE / "installer"))
        import create_demo

        try:
            model = create_demo.make_model()
            create_demo.make_preview()
            glb = trimesh.load(create_demo.MODEL / "mesh.glb", force="mesh")
            stl = trimesh.load(create_demo.MODEL / "mesh.stl", force="mesh")
            with Image.open(create_demo.PREVIEWS / "img_0.png") as image:
                image_size = image.size

            self.assertGreater(len(glb.faces), 100)
            self.assertEqual(len(stl.faces), len(glb.faces))
            self.assertEqual(image_size, (768, 768))
            self.assertGreater(model.extents[2], model.extents[0])
        finally:
            shutil.rmtree(create_demo.ROOT, ignore_errors=True)

    def test_field_build_does_not_delete_existing_dev_outputs(self):
        script = (WORKTREE / "installer" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('Join-Path $Root "release\\$ReleaseId"', script)
        self.assertNotIn('Join-Path $Root "dist"', script)
        self.assertNotIn('Join-Path $Root "build"', script)
        self.assertIn('"keys.txt"', script)


if __name__ == "__main__":
    unittest.main()
