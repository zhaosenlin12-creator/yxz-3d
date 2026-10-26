"""End-to-end flow check against a running backend.

Only the slow preview *generation* is stubbed; the canvas composite, the
image-to-3D call, the export files and the print preflight all run for real.

    python tests/e2e_flow.py --base http://127.0.0.1:8010 --session fe184ddd3b1d
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


WORKTREE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--session", default="", help="an existing session that holds real previews")
    parser.add_argument("--out", default=str(WORKTREE / "logs" / "browser-qa"))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = []

    def check(condition, label):
        if condition:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}")
            failures.append(label)
        return bool(condition)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: print(f"  PAGEERROR  {str(error)[:200]}"))
        page.goto(args.base, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#step-workbench.active", timeout=15000)

        if not args.session:
            print("No --session given; nothing to do.")
            browser.close()
            return 0

        session = args.session
        preview_path = f"/api/data/{session}/previews/img_0.png"
        status = page.evaluate(
            "async (path) => (await fetch(path)).status", preview_path)
        if not check(status == 200, f"real preview is reachable at {preview_path}"):
            browser.close()
            return 1

        def handle_previews(route):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"session_id": session, "queued": True}))

        def handle_progress(route):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"events": [], "latest": {"step": "done", "message": "done"}}))

        def handle_result(route):
            body = {
                "session_id": session,
                "ready": True,
                "previews": [{"index": 0, "path": preview_path, "b64": ""}],
                "specs": [{"caption": "real preview"}],
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route(lambda url: url.split("?")[0].endswith("/api/previews_v2"), handle_previews)
        page.route(lambda url: "/api/progress/" in url, handle_progress)
        page.route(lambda url: url.split("?")[0].endswith(f"/api/session/{session}/result"), handle_result)

        print("\n[1] chat hands a real preview to the canvas")
        page.fill("#chat-input", "e2e canvas composite")
        page.click("#btn-chat-send")
        page.wait_for_selector(".chat-preview", timeout=20000)
        check(True, "preview set is shown")
        page.click(".chat-preview-actions button:has-text('放入画布')")
        check(page.locator("#canvas-world .canvas-node.preview").count() == 1,
              "the real preview is on the canvas")

        print("\n[2] canvas composite drives a real 3D generation")
        page.select_option("#workbench-engine", "cartoon")
        page.click("#btn-canvas-model")
        page.wait_for_function(
            "() => document.querySelectorAll('#workbench-model-versions button').length > 0",
            timeout=300000)
        versions = page.locator("#workbench-model-versions button").count()
        check(versions >= 1, f"a model version was created ({versions})")

        print("\n[3] export files match the generated model")
        project = None
        for _ in range(30):
            projects = page.evaluate(
                "async () => (await (await fetch('/api/projects')).json()).projects")
            for candidate in projects:
                detail = page.evaluate(
                    "async (id) => (await (await fetch('/api/projects/' + id)).json())",
                    candidate["id"])
                if detail.get("versions"):
                    project = detail
                    break
            if project:
                break
            page.wait_for_timeout(1000)
        check(project is not None, "the project records the model version")
        if project is None:
            page.screenshot(path=str(out_dir / "e2e-workbench.png"), full_page=False)
            browser.close()
            print("\nFAILED 1 check(s):\n  - the project records the model version")
            return 1
        versions = project.get("versions", [])
        check(bool(versions), f"project stores {len(versions)} version(s)")
        if versions:
            sid = versions[-1]["sid"]
            for fmt, marker in (("stl", b""), ("glb", b"glTF")):
                response = page.request.get(f"{args.base}/api/export/{sid}/{fmt}")
                body = response.body()
                check(response.status == 200 and len(body) > 0,
                      f"{fmt.upper()} export exists ({len(body)} bytes)")
                if fmt == "stl":
                    import struct
                    triangles = struct.unpack("<I", body[80:84])[0] if len(body) >= 84 else 0
                    check(triangles > 0 and len(body) == 84 + triangles * 50,
                          f"STL export is a binary mesh with {triangles} triangles")
            preflight = page.request.get(f"{args.base}/api/printability/{sid}")
            payload = preflight.json()
            check(preflight.status == 200, "print preflight answers")
            check(payload.get("ready") is True,
                  f"print preflight is green ({payload.get('checks')})")
            check(len(payload.get("extents_mm", [])) == 3, "preflight reports the model size")

        page.screenshot(path=str(out_dir / "e2e-workbench.png"), full_page=False)
        browser.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("End-to-end flow passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
