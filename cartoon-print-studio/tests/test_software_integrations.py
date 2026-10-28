import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import software_integrations


class SoftwareDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        # The registry / shortcut lookup is memoised for a few minutes, so a
        # lookup from an earlier test would still be cached here and the
        # patched candidates below would never be looked at.
        software_integrations._discovery_cache["value"] = None
        software_integrations._discovery_cache["expires_at"] = 0.0

    def executable(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return str(path)

    def detect(self, **env):
        names = ("BAMBU_STUDIO_EXE", "XTOOL_STUDIO_EXE", "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)")
        with patch.dict(os.environ, {name: "" for name in names}, clear=False):
            with patch.dict(os.environ, env, clear=False):
                return {tool["id"]: tool for tool in software_integrations.detect_software()}

    def test_bambu_and_xtool_environment_overrides_require_existing_executables(self):
        bambu = self.executable("bambu.exe")
        xtool = self.executable("xtool.exe")
        with patch.object(software_integrations, "_windows_registry_candidates", return_value={"bambu": [], "xtool": []}), patch.object(
            software_integrations, "_shortcut_candidates", return_value={"bambu": [], "xtool": []}
        ):
            tools = self.detect(BAMBU_STUDIO_EXE=bambu, XTOOL_STUDIO_EXE=xtool)
        self.assertEqual(tools["bambu"]["path"], bambu)
        self.assertEqual(tools["xtool"]["path"], xtool)
        self.assertTrue(tools["bambu"]["available"])
        self.assertTrue(tools["xtool"]["available"])
        self.assertEqual(tools["xtool"]["formats"], ["png", "svg"])

        with patch.object(software_integrations, "_windows_registry_candidates", return_value={"bambu": [], "xtool": []}), patch.object(
            software_integrations, "_shortcut_candidates", return_value={"bambu": [], "xtool": []}
        ):
            tools = self.detect(BAMBU_STUDIO_EXE=str(self.root / "missing-bambu.exe"), XTOOL_STUDIO_EXE=str(self.root / "missing-xtool.exe"))
        self.assertFalse(tools["bambu"]["available"])
        self.assertIsNone(tools["bambu"]["path"])
        self.assertFalse(tools["xtool"]["available"])
        self.assertIsNone(tools["xtool"]["path"])

    def test_registry_and_shortcut_candidates_can_resolve_installations(self):
        bambu = self.executable("registry/bambu-studio.exe")
        xtool = self.executable("shortcut/xtool-studio.exe")
        with patch.object(software_integrations, "_windows_registry_candidates", create=True, return_value={"bambu": [bambu], "xtool": []}), patch.object(
            software_integrations, "_shortcut_candidates", create=True, return_value={"bambu": [], "xtool": [xtool]}
        ):
            tools = self.detect()
        self.assertEqual(tools["bambu"]["path"], bambu)
        self.assertEqual(tools["xtool"]["path"], xtool)

    def test_existing_software_public_fields_and_formats_are_preserved(self):
        tools = self.detect()
        self.assertEqual(set(tools), {"bambu", "orca", "prusa", "cura", "blender", "lightburn", "lasergrbl", "xtool"})
        expected = {
            "orca": ("OrcaSlicer", "3d-print", ["stl", "obj", "3mf"]),
            "prusa": ("PrusaSlicer", "3d-print", ["stl", "obj", "3mf"]),
            "cura": ("UltiMaker Cura", "3d-print", ["stl", "obj"]),
            "blender": ("Blender", "3d-edit", ["glb", "obj", "stl"]),
            "lightburn": ("LightBurn", "laser", ["svg", "dxf", "png"]),
            "lasergrbl": ("LaserGRBL", "laser", ["svg", "png"]),
        }
        for tool_id, (name, kind, formats) in expected.items():
            with self.subTest(tool=tool_id):
                self.assertEqual(
                    set(tools[tool_id]),
                    {"id", "name", "kind", "available", "path", "formats", "verifiedFormats",
                     "overridden", "override", "overrideMissing"},
                )
                self.assertEqual((tools[tool_id]["name"], tools[tool_id]["kind"], tools[tool_id]["formats"]), (name, kind, formats))

    def test_only_formats_verified_on_this_machine_are_advertised(self):
        tools = self.detect()
        # Bambu Studio has no GLB importer, so GLB must never be claimed.
        self.assertNotIn("glb", tools["bambu"]["formats"])
        self.assertEqual(tools["bambu"]["verifiedFormats"], ["stl"])
        self.assertEqual(tools["xtool"]["verifiedFormats"], ["png", "svg"])
        # A tool we could not test on this machine advertises nothing as verified.
        self.assertEqual(tools["blender"]["verifiedFormats"], [])

    def test_user_corrected_path_wins_and_survives_a_restart(self):
        executable = self.executable("custom/bambu-studio.exe")
        with patch.dict(os.environ, {"CARTOON_DATA_DIR": str(self.root / "data")}, clear=False):
            software_integrations.save_override("bambu", executable)
            tools = self.detect()
            self.assertEqual(tools["bambu"]["path"], executable)
            self.assertTrue(tools["bambu"]["available"])
            self.assertTrue(tools["bambu"]["overridden"])
            self.assertFalse(tools["bambu"]["overrideMissing"])

            # A fresh process reads the same file back.
            with patch.dict(os.environ, {"CARTOON_DATA_DIR": str(self.root / "data")}, clear=False):
                reloaded = self.detect()
            self.assertEqual(reloaded["bambu"]["path"], executable)

            # Clearing the override falls back to automatic detection.
            with patch.dict(os.environ, {"CARTOON_DATA_DIR": str(self.root / "data")}, clear=False):
                software_integrations.clear_override("bambu")
                restored = self.detect()
            self.assertFalse(restored["bambu"]["overridden"])

    def test_broken_corrected_path_is_reported_instead_of_pretending_to_exist(self):
        missing = str(self.root / "gone" / "bambu-studio.exe")
        with patch.dict(os.environ, {"CARTOON_DATA_DIR": str(self.root / "data")}, clear=False):
            software_integrations.save_override("bambu", missing)
            tools = self.detect()
        self.assertFalse(tools["bambu"]["available"])
        self.assertIsNone(tools["bambu"]["path"])
        self.assertTrue(tools["bambu"]["overrideMissing"])
        self.assertEqual(tools["bambu"]["override"], missing)

    def test_override_file_that_is_broken_is_ignored(self):
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "software_paths.json").write_text("{not json", encoding="utf-8")
        with patch.dict(os.environ, {"CARTOON_DATA_DIR": str(data)}, clear=False):
            self.assertEqual(software_integrations.load_overrides(), {})
            tools = self.detect()
        self.assertFalse(any(tool["overridden"] for tool in tools.values()))


if __name__ == "__main__":
    unittest.main()
