"""Tripo3D OpenAPI client.

Calls https://api.tripo3d.ai/v2/openapi:
  - POST /upload            multipart PNG/JPG upload -> {"image_token": "..."}
  - POST /task              create generation task
  - GET  /task/{task_id}    poll status

Task type for image_to_model. Output URLs expire in 5 minutes — we
download GLB + PBR GLB immediately and convert to STL with trimesh.
"""
from __future__ import annotations

import os, re, time, json, base64, urllib.request, urllib.error, urllib.parse
from typing import Optional, Dict, Any, List

BASE = "https://api.tripo3d.ai/v2/openapi"

# ---------------------------------------------------------------------------
# Key loading (mirror api_image.py pattern: env override + key.txt fallback)
# ---------------------------------------------------------------------------
# Prefer <install>/keys.txt, fall back to ~/Desktop/key.txt (Windows convenience)
_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEYFILE = (
    os.path.join(_ROOT, "keys.txt")
    if os.path.isfile(os.path.join(_ROOT, "keys.txt"))
    else os.path.expanduser(r"~\Desktop\key.txt")
)
API_KEY = os.environ.get("TRIPO3D_KEY", "").strip()


def _load_key_from_file() -> str:
    if not os.path.isfile(_KEYFILE):
        return ""
    try:
        with open(_KEYFILE, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return ""
    # look for explicit tripo marker
    for line in txt.splitlines():
        low = line.lower()
        if "tripo" in low and ("tsk_" in line):
            m = re.search(r"tsk_[A-Za-z0-9_]+", line)
            if m:
                return m.group(0)
    # fallback: any tsk_ token in the file
    m = re.search(r"tsk_[A-Za-z0-9_]{8,}", txt)
    if m:
        return m.group(0)
    return ""


if not API_KEY:
    API_KEY = _load_key_from_file()


# ---------------------------------------------------------------------------
# HTTP helpers (use stdlib so no extra deps required)
# ---------------------------------------------------------------------------
#
# A blocked or offline provider must not cost the user a minute of waiting
# for every attempt. The first connection error puts the provider on a short
# cooldown: later calls fail immediately with a readable message until a
# probe succeeds again.
_UNREACHABLE_UNTIL = 0.0
_UNREACHABLE_COOLDOWN = 120.0


def provider_unreachable() -> bool:
    """True while the provider is known to be unreachable."""
    return time.time() < _UNREACHABLE_UNTIL


def _mark_unreachable() -> None:
    global _UNREACHABLE_UNTIL
    _UNREACHABLE_UNTIL = time.time() + _UNREACHABLE_COOLDOWN


def _mark_reachable() -> None:
    global _UNREACHABLE_UNTIL
    _UNREACHABLE_UNTIL = 0.0


def _is_connection_failure(error: Exception) -> bool:
    """Tell a network failure apart from an application-level rejection."""
    if isinstance(error, urllib.error.HTTPError):
        return False
    reason = getattr(error, "reason", None)
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    if isinstance(reason, (TimeoutError, ConnectionError, OSError)):
        return True
    text = str(error).lower()
    return "timed out" in text or "timeout" in text or "connection" in text or "unreachable" in text


def _request(method: str, path: str, *, body: Optional[bytes] = None,
             headers: Optional[Dict[str, str]] = None,
             timeout: float = 60.0, retries: int = 2, backoff: float = 1.5) -> Dict[str, Any]:
    """HTTP wrapper with retry+backoff for transient failures.

    Retries up to `retries` times on connection errors and HTTP 5xx.
    HTTP 4xx is not retried (caller asked for something invalid).
    Each attempt has `timeout` seconds; backoff doubles from `backoff`s.
    """
    if provider_unreachable():
        raise RuntimeError(
            "Tripo 当前网络不可达（刚刚连接失败），请检查网络或改用其他引擎"
        )
    url = BASE + path
    h = {"Authorization": "Bearer " + API_KEY}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "ignore")
            _mark_reachable()
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
        except urllib.error.HTTPError as e:
            try:
                err = e.read().decode("utf-8", "ignore")
            except Exception:
                err = str(e.reason)
            if 400 <= e.code < 500:
                raise RuntimeError(f"Tripo HTTP {e.code} on {method} {path}: {err[:400]}")
            last_err = RuntimeError(f"Tripo HTTP {e.code} on {method} {path}: {err[:200]}")
            print(f"[tripo] attempt {attempt+1}/{retries+1} got {e.code}, retrying in {backoff:.1f}s", flush=True)
        except Exception as e:
            last_err = RuntimeError(f"Tripo {method} {path} failed: {e}")
            if _is_connection_failure(e):
                _mark_unreachable()
            print(f"[tripo] attempt {attempt+1}/{retries+1} {type(e).__name__}: {str(e)[:160]}", flush=True)
            if provider_unreachable():
                break
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    assert last_err is not None
    raise last_err


def _multipart(filename: str, content: bytes, mime: str = "image/png") -> tuple[bytes, str]:
    boundary = "----tripo" + os.urandom(8).hex()
    CRLF = b"\r\n"
    parts: List[bytes] = [
        ("--" + boundary).encode("ascii"),
        b'Content-Disposition: form-data; name="file"; filename="' + filename.encode("utf-8") + b'"',
        ("Content-Type: " + mime).encode("ascii"),
        b"",
        content,
        ("--" + boundary + "--").encode("ascii"),
        b"",
    ]
    body = CRLF.join(parts)
    return body, "multipart/form-data; boundary=" + boundary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_balance(timeout: float = 15.0, retries: int = 2) -> Dict[str, Any]:
    """Query remaining credits from Tripo3D.

    `timeout`/`retries` are exposed so callers that only need a quick
    availability signal (for example the health probe shown at startup)
    can bound the request instead of blocking on the full retry ladder.
    """
    if not API_KEY:
        return {"ok": False, "error": "tripo3d key not configured"}
    try:
        j = _request("GET", "/user/balance", timeout=timeout, retries=retries)
        if j.get("code", 0) != 0:
            return {"ok": False, "error": j.get("msg") or str(j)}
        data = j.get("data") or {}
        return {
            "ok": True,
            "balance": int(data.get("balance", 0)),
            "frozen": int(data.get("frozen", 0)),
            "total": int(data.get("balance", 0)) + int(data.get("frozen", 0)),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def health() -> Dict[str, Any]:
    return {
        "key_loaded": bool(API_KEY),
        "key_preview": (API_KEY[:14] + "...") if API_KEY else None,
        "base": BASE,
    }


def upload_image(local_path: str) -> str:
    """Upload an image file to Tripo3D, return image_token."""
    if not API_KEY:
        raise RuntimeError("TRIPO3D key not configured (set TRIPO3D_KEY env or check key.txt)")
    with open(local_path, "rb") as f:
        blob = f.read()
    if len(blob) < 256:
        raise RuntimeError(f"image too small ({len(blob)} bytes): {local_path}")
    mime = "image/jpeg" if local_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    body, ctype = _multipart(os.path.basename(local_path), blob, mime=mime)
    # A blocked provider should fail in seconds, not minutes: the caller
    # falls back to a local engine as soon as this returns.
    j = _request("POST", "/upload", body=body, headers={"Content-Type": ctype}, timeout=25.0, retries=1)
    code = (j.get("code") if isinstance(j, dict) else None)
    data = j.get("data") if isinstance(j, dict) else None
    if code not in (None, 0) and j.get("code", 0) != 0:
        raise RuntimeError(f"Tripo upload non-zero code={code}: {j}")
    token = None
    if isinstance(data, dict):
        token = data.get("image_token") or data.get("file_token")
    if not token:
        # older shape
        token = j.get("image_token")
    if not token:
        raise RuntimeError(f"Tripo upload returned no image_token: {j}")
    return token


def create_image_to_model(image_token: str, *,
                          model_version: str = "v3.1-20260211",
                          texture: bool = True,
                          pbr: bool = True,
                          texture_quality: str = "detailed",
                          face_limit: Optional[int] = None,
                          quad: bool = False,
                          auto_size: bool = False) -> str:
    """Create image_to_model task, return task_id."""
    body: Dict[str, Any] = {
        "type": "image_to_model",
        "file": {"type": "png", "file_token": image_token},
        "model_version": model_version,
        "texture": texture,
        "pbr": pbr,
        "texture_quality": texture_quality,
        "quad": quad,
        "auto_size": auto_size,
    }
    if face_limit:
        body["face_limit"] = face_limit
    data = json.dumps(body).encode("utf-8")
    j = _request("POST", "/task", body=data,
                 headers={"Content-Type": "application/json"}, timeout=60.0)
    code = j.get("code", 0)
    if code != 0:
        raise RuntimeError(f"Tripo create task failed code={code}: {j}")
    payload = j.get("data") or {}
    tid = payload.get("task_id")
    if not tid:
        raise RuntimeError(f"Tripo create task returned no task_id: {j}")
    return tid


def get_task(task_id: str) -> Dict[str, Any]:
    j = _request("GET", f"/task/{task_id}", timeout=30.0)
    if j.get("code", 0) != 0:
        raise RuntimeError(f"Tripo get_task failed: {j}")
    return j.get("data") or {}


def poll_until_done(task_id: str, *,
                    poll_interval: float = 3.0,
                    max_wait: float = 240.0,
                    on_poll=None,
                    network_retries: int = 5,
                    on_persistent_failure=None) -> Dict[str, Any]:
    """Poll until status is success/failed/expired/banned.

    on_poll(task_dict) -> None, called after each poll.
    on_persistent_failure(fail_count, last_err) -> None, called after
        a stretch of consecutive network failures so the caller can
        emit a progress event instead of looking hung.
    Returns the final task dict.

    Resilience: Tripo LB occasionally drops SSL/TLS mid-poll
    (UNEXPECTED_EOF_WHILE_READING). Each individual get_task is
    retried up to network_retries times before counting as a single
    failed poll. We only abort after max_poll_failures failed polls
    in a row, since the task is still alive on the server.
    """
    deadline = time.time() + max_wait
    last = None
    max_poll_failures = 6
    consecutive_poll_failures = 0
    while time.time() < deadline:
        t = None
        last_err = None
        for attempt in range(network_retries):
            try:
                t = get_task(task_id)
                break
            except Exception as e:
                last_err = e
                if attempt < network_retries - 1:
                    time.sleep(min(2.0, 0.6 * (attempt + 1)))
        if t is None:
            consecutive_poll_failures += 1
            last = {"status": "running",
                    "progress": last.get("progress") if isinstance(last, dict) else 0,
                    "_network_error": str(last_err)[:160]}
            if on_persistent_failure:
                try:
                    on_persistent_failure(consecutive_poll_failures, last_err)
                except Exception:
                    pass
            print(f"[tripo] poll failure x{consecutive_poll_failures} for {task_id}: {last_err}", flush=True)
            if consecutive_poll_failures >= max_poll_failures:
                raise RuntimeError(
                    f"Tripo polling lost connection {consecutive_poll_failures}x in a row for {task_id}: {last_err}"
                )
            time.sleep(poll_interval * 2)
            continue
        consecutive_poll_failures = 0
        last = t
        if on_poll:
            on_poll(t)
        status = (t.get("status") or "").lower()
        if status in ("success", "succeeded", "done"):
            return t
        if status in ("failed", "failure", "banned", "expired", "cancelled", "canceled"):
            raise RuntimeError(f"Tripo task {task_id} ended with status={status}: {t}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Tripo task {task_id} did not finish in {max_wait}s; last={last}")


def _download(url: str, out_path: str, timeout: float = 60.0) -> int:
    """Download a file from a presigned URL (no auth header needed)."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        with open(out_path, "wb") as f:
            total = 0
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
    return total


def download_outputs(task_result: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    """Download model + base + pbr (whichever exist) into out_dir. Returns paths."""
    os.makedirs(out_dir, exist_ok=True)
    out = task_result.get("output") or {}
    paths: Dict[str, str] = {}
    # primary outputs
    candidates = [
        ("pbr_model", "model_pbr.glb"),
        ("base_model", "model.glb"),
        ("model", "model.glb"),
        ("mesh", "mesh.glb"),
    ]
    primary_done = False
    for key, fname in candidates:
        url = out.get(key)
        if not url or primary_done and key != "pbr_model":
            continue
        try:
            n = _download(url, os.path.join(out_dir, fname), timeout=120.0)
            paths[fname] = os.path.join(out_dir, fname)
            if key in ("base_model", "model", "mesh"):
                primary_done = True
        except Exception as e:
            print(f"[tripo] download {key} failed: {e}", flush=True)
    return paths


def image_to_model(local_path: str, out_dir: str, *,
                   model_version: str = "v3.1-20260211",
                   texture: bool = True,
                   pbr: bool = True,
                   texture_quality: str = "detailed",
                   face_limit: Optional[int] = None,
                   max_wait: float = 240.0,
                   on_poll=None) -> Dict[str, Any]:
    """High-level: upload + create + poll + download."""
    image_token = upload_image(local_path)
    task_id = create_image_to_model(image_token,
                                    model_version=model_version,
                                    texture=texture, pbr=pbr,
                                    texture_quality=texture_quality,
                                    face_limit=face_limit)
    # Persist task_id immediately so the user can resume if polling dies.
    try:
        import json as _json_s
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "_tripo_state.json"), "w", encoding="utf-8") as _f:
            _json_s.dump({"task_id": task_id, "image_token": image_token,
                          "model_version": model_version}, _f, ensure_ascii=False)
    except Exception:
        pass
    task = poll_until_done(task_id, max_wait=max_wait, on_poll=on_poll)
    paths = download_outputs(task, out_dir)
    if not paths:
        raise RuntimeError(f"Tripo succeeded but no GLB downloaded: {task}")
    return {
        "task_id": task_id,
        "image_token": image_token,
        "model_version": model_version,
        "progress": task.get("progress"),
        "raw": task,
        "files": paths,
    }


# ---------------------------------------------------------------------------
# Mesh post-processing for 3D printing
# ---------------------------------------------------------------------------
def _scale_to_print_size(mesh, target_height_mm: float = 70.0) -> Any:
    """Scale mesh so the longest vertical extent equals target_height_mm."""
    import trimesh
    ext = mesh.extents
    if ext[1] <= 0:
        return mesh
    # y-up: assume model is upright; use Y extent (height) as reference
    scale = target_height_mm / ext[1]
    mesh.apply_scale(scale)
    # Re-center on print bed: bottom touches z=0
    bounds = mesh.bounds
    mesh.apply_translation([0, 0, -bounds[0][2]])
    return mesh


def _clean_for_print(mesh, target_height_mm: float = 70.0) -> Any:
    """Drop disconnected fragments, fill obvious holes, scale to print size."""
    import trimesh
    # drop debris
    components = mesh.split(only_watertight=False)
    if len(components) > 1:
        components.sort(key=lambda c: len(c.faces), reverse=True)
        mesh = components[0]
    # try to fill holes for nicer slicing
    try:
        mesh.fill_holes()
    except Exception:
        pass
    # remove degenerate faces
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    # scale to print size and place on plate
    mesh = _scale_to_print_size(mesh, target_height_mm)
    return mesh


def process_for_print(pbr_glb_path: str, out_dir: str, *,
                      target_height_mm: float = 70.0,
                      keep_visual: bool = True) -> Dict[str, str]:
    """Convert a Tripo3D PBR GLB to printable STL + OBJ + GLB.

    - GLB keeps PBR material & textures (for viewer in browser).
    - STL/OBJ are colorless but print-ready.
    - Mesh is centered on print bed with bottom on z=0.
    - All exported at target_height_mm in mm units.
    """
    import trimesh
    os.makedirs(out_dir, exist_ok=True)
    mesh = trimesh.load(pbr_glb_path, force="mesh", process=False)
    # Detach visual so we can build a clean printable copy
    printable = mesh.copy()
    printable = _clean_for_print(printable, target_height_mm=target_height_mm)

    paths: Dict[str, str] = {}
    stl_path = os.path.join(out_dir, "mesh.stl")
    obj_path = os.path.join(out_dir, "mesh.obj")
    printable.export(stl_path)
    paths["stl"] = stl_path
    printable.export(obj_path)
    paths["obj"] = obj_path

    # GLB keeps visual (PBR textures) — viewers in the browser use this
    if keep_visual:
        glb_path = os.path.join(out_dir, "mesh.glb")
        # Apply same transform to the visual mesh so they line up
        visual = mesh.copy()
        ext = visual.extents
        if ext[1] > 0:
            scale = target_height_mm / ext[1]
            visual.apply_scale(scale)
            bounds = visual.bounds
            visual.apply_translation([0, 0, -bounds[0][2]])
        try:
            visual.export(glb_path)
            paths["glb"] = glb_path
        except Exception as e:
            print(f"[tripo] glb export failed: {e}", flush=True)

    paths["faces"] = str(len(printable.faces))
    paths["vertices"] = str(len(printable.vertices))
    paths["extents_mm"] = ",".join(f"{x:.1f}" for x in printable.extents)
    return paths



if __name__ == "__main__":
    h = health()
    print("health:", h)
    if len(sys.argv) > 1:
        result = image_to_model(sys.argv[1], "_tripo_smoke")
        print(json.dumps({k: v for k, v in result.items() if k != "raw"}, indent=2))

