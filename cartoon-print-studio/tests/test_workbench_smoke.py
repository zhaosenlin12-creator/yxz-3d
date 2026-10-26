import os
import base64
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


WORKTREE = Path(__file__).resolve().parents[1]
TEST_DATA = tempfile.TemporaryDirectory(prefix="cartoon-workbench-tests-")
os.environ["CARTOON_ROOT"] = str(WORKTREE)
os.environ["CARTOON_FRONTEND_DIR"] = str(WORKTREE / "frontend")
os.environ["CARTOON_DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(WORKTREE / "backend"))

import server


class WorkbenchSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.sid = "smoke-session-01"
        cls.session = Path(server.DATA) / cls.sid
        (cls.session / "previews").mkdir(parents=True, exist_ok=True)
        (cls.session / "model").mkdir(parents=True, exist_ok=True)

        from PIL import Image
        preview = cls.session / "previews" / "img_0.png"
        Image.new("RGB", (2, 2), (255, 255, 255)).save(preview)

    def setUp(self):
        import trimesh

        (self.session / "previews").mkdir(parents=True, exist_ok=True)
        (self.session / "model").mkdir(parents=True, exist_ok=True)
        mesh = trimesh.creation.box(extents=(20, 20, 20))
        mesh.export(self.session / "model" / "mesh.glb")
        mesh.export(self.session / "model" / "mesh.stl")
        mesh.export(self.session / "model" / "mesh.obj")

    def test_health_does_not_require_provider_network(self):
        with patch.object(server.tripo_api, "health", return_value={"key_loaded": False}), patch.object(
            server.tripo_api, "get_balance", return_value={"ok": False}
        ):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_health_returns_while_balance_probe_is_still_blocked(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_probe(**kwargs):
            entered.set()
            release.wait(timeout=3)
            return {"ok": False}

        old_cache = dict(server._BALANCE_CACHE)
        old_running = server._BALANCE_PROBE["running"]
        server._BALANCE_CACHE.update(value=None, ts=0)
        server._BALANCE_PROBE["running"] = False

        def restore_probe():
            release.set()
            deadline = time.monotonic() + 1
            while server._BALANCE_PROBE["running"] and time.monotonic() < deadline:
                time.sleep(0.005)
            server._BALANCE_CACHE.update(old_cache)
            server._BALANCE_PROBE["running"] = old_running

        self.addCleanup(restore_probe)

        with patch.object(server.tripo_api, "health", return_value={"key_loaded": True}), patch.object(
            server.tripo_api, "get_balance", side_effect=blocked_probe
        ):
            started = time.perf_counter()
            response = self.client.get("/api/health")
            elapsed = time.perf_counter() - started

        self.assertTrue(entered.wait(timeout=1))
        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 0.5)
        self.assertTrue(response.json()["tripo3d_checking"])

    def test_tripo_generation_does_not_wait_for_an_unknown_balance(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_probe(**kwargs):
            entered.set()
            release.wait(timeout=3)
            return {"ok": False}

        old_cache = dict(server._BALANCE_CACHE)
        old_running = server._BALANCE_PROBE["running"]
        server._BALANCE_CACHE.update(value=None, ts=0)
        server._BALANCE_PROBE["running"] = False

        def restore_probe():
            release.set()
            deadline = time.monotonic() + 1
            while server._BALANCE_PROBE["running"] and time.monotonic() < deadline:
                time.sleep(0.005)
            server._BALANCE_CACHE.update(old_cache)
            server._BALANCE_PROBE["running"] = old_running

        self.addCleanup(restore_probe)

        with patch.object(server.tripo_api, "API_KEY", "configured"), patch.object(
            server.tripo_api, "get_balance", side_effect=blocked_probe
        ), patch.object(server.tripo_api, "image_to_model", side_effect=RuntimeError("test failure")) as generate, patch.object(
            server.traceback, "print_exc"
        ):
            started = time.perf_counter()
            with self.assertRaises(HTTPException) as raised:
                server.to_3d_tripo(server.ThreeDTripoReq(session_id=self.sid))
            elapsed = time.perf_counter() - started

        self.assertTrue(entered.wait(timeout=1))
        self.assertLess(elapsed, 0.5)
        self.assertNotEqual(raised.exception.status_code, 402)
        generate.assert_called_once()

    def test_demo_model_skips_mesh_conversion_after_first_request(self):
        first = self.client.get("/api/demo")
        self.assertEqual(first.status_code, 200)

        import trimesh
        with patch("trimesh.load", side_effect=AssertionError("mesh should already be prepared")):
            second = self.client.get("/api/demo")

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["session_id"], first.json()["session_id"])

    def test_example_model_is_discoverable(self):
        response = self.client.get("/api/demo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], self.sid)
        self.assertTrue(self.client.get(response.json()["model_url"]).content)

    def test_bundled_example_takes_priority_over_local_recent_sessions(self):
        from PIL import Image

        demo = Path(server.DATA) / "demo"
        (demo / "model").mkdir(parents=True, exist_ok=True)
        (demo / "previews").mkdir(parents=True, exist_ok=True)
        (demo / "model" / "mesh.glb").write_bytes(b"bundled-demo")
        Image.new("RGB", (2, 2), (20, 40, 60)).save(demo / "previews" / "img_0.png")
        (demo / "demo.json").write_text('{"prompt":"bundled prompt"}', encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(demo, ignore_errors=True))

        response = self.client.get("/api/demo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "demo")
        self.assertEqual(response.json()["prompt"], "bundled prompt")
        self.assertEqual(self.client.get(response.json()["model_url"]).content, b"bundled-demo")
        self.assertEqual(self.client.get(response.json()["preview_url"]).status_code, 200)

    def test_bundled_example_resolves_printable_exports_and_preflight(self):
        import trimesh

        demo = Path(server.DATA) / "demo"
        model_dir = demo / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        mesh = trimesh.creation.box(extents=(24, 24, 50))
        mesh.export(model_dir / "mesh.glb")
        mesh.export(model_dir / "mesh.stl")
        mesh.export(model_dir / "mesh.obj")

        try:
            for fmt in ("glb", "stl", "obj"):
                response = self.client.get(f"/api/export/demo/{fmt}")
                self.assertEqual(response.status_code, 200, fmt)
                self.assertGreater(len(response.content), 0)
            preflight = self.client.get("/api/printability/demo")
            self.assertEqual(preflight.status_code, 200)
            self.assertTrue(preflight.json()["checks"]["has_faces"])
        finally:
            __import__("shutil").rmtree(demo, ignore_errors=True)

    def test_preview_result_and_static_file_are_available(self):
        response = self.client.get(f"/api/session/{self.sid}/result")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["previews"]), 1)
        image = self.client.get(f"/api/data/{self.sid}/previews/img_0.png")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")

    def test_model_exports_are_available(self):
        for fmt in ("stl", "obj", "glb"):
            with self.subTest(fmt=fmt):
                response = self.client.get(f"/api/export/{self.sid}/{fmt}")
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.content), 0)

    def test_edited_model_upload_replaces_all_export_formats_and_print_preflight(self):
        import trimesh
        merged = trimesh.creation.box(extents=(36, 24, 18))
        before = self.client.get(f"/api/export/{self.sid}/stl").content
        files = {
            "stl": ("edited.stl", merged.export(file_type="stl"), "model/stl"),
            "obj": ("edited.obj", merged.export(file_type="obj").encode(), "text/plain"),
            "glb": ("edited.glb", merged.export(file_type="glb"), "model/gltf-binary"),
        }
        response = self.client.put(f"/api/session/{self.sid}/edited-model", files=files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["extents_mm"], [36.0, 24.0, 18.0])
        self.assertNotEqual(self.client.get(f"/api/export/{self.sid}/stl").content, before)
        self.assertIn("v ", self.client.get(f"/api/export/{self.sid}/obj").text)
        self.assertTrue(self.client.get(f"/api/export/{self.sid}/glb").content.startswith(b"glTF"))
        self.assertTrue(self.client.get(f"/api/printability/{self.sid}").json()["ready"])
        with patch.object(server.bambu, "open_in_bambu", return_value={"ok": True}) as open_file:
            self.client.post("/api/print", json={"session_id": self.sid})
        self.assertEqual(Path(open_file.call_args.args[0]).read_bytes(), files["stl"][1])

    def test_edited_model_rejects_invalid_glb_without_replacing_current_files(self):
        import trimesh

        before = self.client.get(f"/api/export/{self.sid}/stl").content
        mesh = trimesh.creation.box()
        response = self.client.put(f"/api/session/{self.sid}/edited-model", files={
            "stl": ("edited.stl", mesh.export(file_type="stl"), "model/stl"),
            "obj": ("edited.obj", mesh.export(file_type="obj").encode(), "text/plain"),
            "glb": ("bad.glb", b"not a glb", "model/gltf-binary"),
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/api/export/{self.sid}/stl").content, before)

    def test_printability_reports_mesh_dimensions(self):
        response = self.client.get(f"/api/printability/{self.sid}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ready"])
        self.assertTrue(body["checks"]["watertight"])
        self.assertEqual(body["extents_mm"], [20.0, 20.0, 20.0])

    def test_print_route_only_hands_existing_stl_to_launcher(self):
        expected = {"ok": True, "method": "stub"}
        with patch.object(server.bambu, "open_in_bambu", return_value=expected) as open_file:
            response = self.client.post("/api/print", json={"session_id": self.sid})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(Path(open_file.call_args.args[0]), self.session / "model" / "mesh.stl")

    def test_viewers_load_three_from_local_vendor(self):
        for name in ("index.html", "viewer.html"):
            with self.subTest(page=name):
                html = (WORKTREE / "frontend" / name).read_text(encoding="utf-8")
                self.assertNotIn("cdn.jsdelivr.net/npm/three", html)
                self.assertIn("./vendor/three/build/three.module.js", html)

    def test_workbench_exposes_chat_canvas_image_and_history_controls(self):
        html = (WORKTREE / "frontend" / "index.html").read_text(encoding="utf-8")
        expected = (
            "conversation-list", "chat-input", "btn-chat-send", "canvas-viewport",
            "canvas-world", "btn-canvas-note", "btn-canvas-draw", "canvas-image-input",
            "btn-canvas-undo", "btn-canvas-redo", "btn-canvas-fit", "btn-canvas-reset",
            "btn-canvas-model",
        )
        missing = [element_id for element_id in expected if f'id="{element_id}"' not in html]
        self.assertEqual(missing, [])

    def test_project_create_read_update_list_and_delete(self):
        created = self.client.post("/api/projects", json={
            "name": "test project",
            "messages": [{"role": "user", "content": "blue mascot"}],
            "prompt": "blue mascot",
            "previews": [],
            "versions": [],
            "canvas": {"elements": []},
            "selection": None,
        })
        self.assertEqual(created.status_code, 201)
        project = created.json()
        project_id = project["id"]
        self.assertEqual(project["schemaVersion"], 1)
        self.assertEqual(project["messages"][0]["content"], "blue mascot")

        listed = self.client.get("/api/projects")
        self.assertEqual(listed.status_code, 200)
        self.assertIn(project_id, [item["id"] for item in listed.json()["projects"]])

        project["name"] = "updated project"
        updated = self.client.put(f"/api/projects/{project_id}", json=project)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "updated project")

        restored = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["name"], "updated project")
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}").status_code, 404)

    def test_project_rejects_invalid_ids_and_external_media_paths(self):
        self.assertEqual(self.client.get("/api/projects/../../keys.txt").status_code, 404)
        response = self.client.post("/api/projects", json={
            "name": "unsafe",
            "messages": [],
            "previews": [{"path": "/api/data/../../keys.txt"}],
            "versions": [],
            "canvas": {"elements": []},
        })
        self.assertEqual(response.status_code, 422)

    def test_project_rejects_out_of_range_canvas_and_version_values(self):
        response = self.client.post("/api/projects", json={
            "name": "invalid geometry",
            "messages": [],
            "previews": [],
            "versions": [{
                "id": "version-01",
                "sid": "version-01",
                "meshUrl": "/api/data/version-01/model/mesh.glb",
                "primitives": [{"kind": "cube", "x": 1e9}],
            }],
            "activeVersionId": "version-01",
            "canvas": {"elements": [], "viewport": {"zoom": 99}},
        })
        self.assertEqual(response.status_code, 422)

    def test_project_reports_missing_media_without_dropping_reference(self):
        created = self.client.post("/api/projects", json={
            "name": "missing media",
            "messages": [],
            "previews": [{"path": "/api/data/0123456789ab/previews/img_0.png"}],
            "versions": [],
            "canvas": {"elements": []},
        })
        self.assertEqual(created.status_code, 201)
        response = self.client.get(f"/api/projects/{created.json()['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["previews"][0]["path"], "/api/data/0123456789ab/previews/img_0.png")
        self.assertTrue(response.json()["missingReferences"])

    def test_project_images_are_validated_stored_and_restored(self):
        from io import BytesIO
        from PIL import Image

        created = self.client.post("/api/projects", json={
            "name": "canvas image",
            "messages": [],
            "previews": [],
            "versions": [],
            "canvas": {"elements": []},
        })
        project_id = created.json()["id"]
        encoded = BytesIO()
        Image.new("RGB", (3, 2), (40, 120, 200)).save(encoded, format="PNG")
        upload = self.client.post(
            f"/api/projects/{project_id}/media",
            files={"image": ("drawing.png", encoded.getvalue(), "image/png")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        media = upload.json()
        self.assertEqual((media["width"], media["height"]), (3, 2))

        project = created.json()
        project["canvas"]["elements"] = [{"type": "image", "path": media["path"], "x": 0, "y": 0, "width": 3, "height": 2}]
        updated = self.client.put(f"/api/projects/{project_id}", json=project)
        self.assertEqual(updated.status_code, 200)
        restored = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(restored.json()["missingReferences"], [])
        self.assertEqual(self.client.get(media["path"]).content, encoded.getvalue())

        rejected = self.client.post(
            f"/api/projects/{project_id}/media",
            files={"image": ("unsafe.svg", b"<svg></svg>", "image/svg+xml")},
        )
        self.assertEqual(rejected.status_code, 415)

    def test_prompt_polish_without_provider_keeps_original_text(self):
        with patch.object(server.llm_client, "MINIMAX_API_KEYS", [""]), patch.object(
            server.llm_client, "DEEPSEEK_API_KEYS", []
        ), patch.object(
            server.llm_client, "_minimax_call"
        ) as call:
            response = self.client.post("/api/prompt/polish", json={"text": "蓝色小猫"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["text"], "蓝色小猫")
        self.assertEqual(payload["reason"], "provider_not_configured")
        self.assertTrue(payload["fallback"]["text"].startswith("蓝色小猫"))
        call.assert_not_called()

    def test_prompt_polish_returns_suggestion_without_replacing_source(self):
        with patch.object(server.llm_client, "MINIMAX_API_KEYS", ["configured"]), patch.object(
            server.llm_client, "_minimax_call", return_value="  蓝色小猫，圆润造型，白色背景  "
        ) as call:
            response = self.client.post("/api/prompt/polish", json={"text": "蓝色小猫"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True,
            "text": "蓝色小猫",
            "suggestion": "蓝色小猫，圆润造型，白色背景",
        })
        self.assertIn("蓝色小猫", call.call_args.args[0])

    def test_prompt_polish_provider_failure_preserves_source(self):
        with patch.object(server.llm_client, "MINIMAX_API_KEYS", ["configured"]), patch.object(
            server.llm_client, "DEEPSEEK_API_KEYS", []
        ), patch.object(
            server.llm_client, "_minimax_call", return_value=None
        ):
            response = self.client.post("/api/prompt/polish", json={"text": "蓝色小猫"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["text"], "蓝色小猫")
        self.assertEqual(payload["reason"], "provider_unavailable")
        self.assertEqual(payload["fallback"]["source"], "local_rules")

    def test_local_polish_keeps_subject_and_adds_print_hints(self):
        suggestion = server.llm_client.polish_prompt_local("蓝色小猫")
        self.assertIn("蓝色小猫", suggestion)
        self.assertIn("纯白背景", suggestion)
        already = server.llm_client.polish_prompt_local("蓝色小猫，纯白背景，卡通风格，完整居中")
        self.assertEqual(already.count("纯白背景"), 1)
        self.assertEqual(already.count("卡通风格"), 1)
        self.assertEqual(already.count("完整居中"), 1)

    def test_session_from_image_stores_the_composed_canvas_png(self):
        from io import BytesIO
        from PIL import Image

        encoded = BytesIO()
        Image.new("RGBA", (12, 9), (10, 20, 30, 255)).save(encoded, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode()
        response = self.client.post("/api/session/from-image", json={
            "image": data_url,
            "svg": "<svg xmlns='http://www.w3.org/2000/svg' width='12' height='9'></svg>",
            "prompt": "canvas composite",
            "source": "canvas",
        })
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual((payload["width"], payload["height"]), (12, 9))
        self.assertEqual(self.client.get(payload["preview_url"]).status_code, 200)
        self.assertEqual(self.client.get(payload["svg_url"]).status_code, 200)
        self.assertNotEqual(payload["session_id"], self.sid)

    def test_session_from_image_rejects_non_image_payloads(self):
        rejected = self.client.post("/api/session/from-image", json={"image": "not-a-data-url"})
        self.assertEqual(rejected.status_code, 400)
        scripted = self.client.post("/api/session/from-image", json={
            "image": "data:image/png;base64,bm90IGFuIGltYWdl",
        })
        self.assertEqual(scripted.status_code, 400)

    def test_software_open_rejects_paths_outside_the_data_directory(self):
        response = self.client.post("/api/software/open", json={
            "software_id": "bambu",
            "session_id": "../../keys",
            "fmt": "stl",
        })
        self.assertEqual(response.status_code, 400)

    def test_session_ids_cannot_escape_the_data_directory(self):
        outside = Path(server.DATA).parent / "escaped-session"
        self.assertFalse(outside.exists())
        # A Windows-style traversal reaches the handler as one path segment;
        # it must be rejected there instead of creating a folder outside data/.
        for session_id in ("..%5C..%5Cescaped-session", "..", "%2e%2e%5Cescaped-session"):
            for suffix in ("stl", "obj", "glb"):
                response = self.client.get(f"/api/export/{session_id}/{suffix}")
                self.assertNotEqual(response.status_code, 200, f"{session_id}/{suffix}")
            result = self.client.get(f"/api/session/{session_id}/result")
            self.assertNotEqual(result.status_code, 200, session_id)
            # The guard itself rejects every traversal shape, whichever way
            # the HTTP layer happens to normalise the URL.
            with self.assertRaises(HTTPException):
                server.session_dir(session_id.replace("%5C", "\\"))
        self.assertFalse(outside.exists(), "no folder is created outside the data directory")

    def test_software_path_can_be_corrected_and_reset(self):
        with tempfile.TemporaryDirectory(prefix="cartoon-software-exe-") as folder:
            executable = Path(folder) / "bambu-studio.exe"
            executable.touch()

            saved = self.client.post("/api/software/path", json={
                "software_id": "bambu",
                "path": str(executable),
            })
            self.assertEqual(saved.status_code, 200)
            tool = next(item for item in saved.json()["tools"] if item["id"] == "bambu")
            self.assertTrue(tool["available"])
            self.assertTrue(tool["overridden"])
            self.assertEqual(tool["path"], str(executable))

            # The corrected path survives a restart because it is stored on disk.
            detected = self.client.get("/api/software/detect").json()["tools"]
            stored = next(item for item in detected if item["id"] == "bambu")
            self.assertEqual(stored["path"], str(executable))

            reset = self.client.delete("/api/software/path/bambu")
            self.assertEqual(reset.status_code, 200)
            restored = next(item for item in reset.json()["tools"] if item["id"] == "bambu")
            self.assertFalse(restored["overridden"])

    def test_software_path_rejects_missing_files_and_unknown_tools(self):
        missing = self.client.post("/api/software/path", json={
            "software_id": "bambu",
            "path": str(Path(server.DATA) / "not-here.exe"),
        })
        self.assertEqual(missing.status_code, 400)

        unknown = self.client.post("/api/software/path", json={
            "software_id": "not-a-tool",
            "path": r"C:\Windows\System32\notepad.exe",
        })
        self.assertEqual(unknown.status_code, 404)

    def test_software_path_rejects_non_executable_files(self):
        not_an_exe = Path(server.DATA) / "notes.txt"
        not_an_exe.write_text("hello", encoding="utf-8")
        response = self.client.post("/api/software/path", json={
            "software_id": "bambu",
            "path": str(not_an_exe),
        })
        self.assertEqual(response.status_code, 400)

    def test_session_fork_keeps_preview_but_creates_isolated_model_version(self):
        forks = []
        for _ in range(2):
            response = self.client.post(f"/api/session/{self.sid}/fork", json={"image_index": 0})
            self.assertEqual(response.status_code, 201)
            fork = response.json()
            forks.append(fork)
            self.assertNotEqual(fork["session_id"], self.sid)
            self.assertEqual(fork["source_session_id"], self.sid)
            self.assertEqual(
                self.client.get(f"/api/data/{fork['session_id']}/previews/img_0.png").status_code,
                200,
            )
            self.assertEqual(
                self.client.get(f"/api/data/{fork['session_id']}/model/mesh.glb").status_code,
                404,
            )
        self.assertNotEqual(forks[0]["session_id"], forks[1]["session_id"])


if __name__ == "__main__":
    unittest.main()
