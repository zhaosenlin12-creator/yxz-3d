"""Tripo3D OpenAPI client.

Tripo runs two regional platforms with different hosts and API versions:

  v3  https://openapi.tripo3d.com/v3      (China / CN console)
      POST /files                      multipart PNG/JPG upload -> file_token
      POST /generation/image-to-model  create generation task
      GET  /tasks/{task_id}            poll status
      GET  /account/balance            credits

  v2  https://api.tripo3d.ai/v2/openapi   (global console)
      POST /upload, POST /task, GET /task/{task_id}, GET /user/balance

An API key belongs to exactly one of the two platforms: a CN key answers
401 on the global host and a global key answers 401 on the CN host. The
client therefore tries the CN platform first and falls back to the global
one, for every configured key.

Task type for image_to_model. Output URLs expire in 5 minutes — we
download GLB + PBR GLB immediately and convert to STL with trimesh.
"""
from __future__ import annotations

import os, re, time, json, base64, urllib.request, urllib.error, urllib.parse
from typing import Optional, Dict, Any, List

BASE_V3 = "https://openapi.tripo3d.com/v3"
BASE_V2 = "https://api.tripo3d.ai/v2/openapi"

#: Which platform the current key belongs to. Flipped automatically when a
#: key is rejected by the active host, and remembered for the next call.
_api_version = "v3"
BASE = BASE_V3


def _base_for(version: str) -> str:
    return BASE_V3 if version == "v3" else BASE_V2


def _set_version(version: str) -> None:
    """Remember which platform the configured keys live on."""
    global _api_version, BASE
    if version != _api_version:
        print(f"[tripo] switching to {version} platform ({_base_for(version)})", flush=True)
    _api_version = version
    BASE = _base_for(version)


def _path(version: str, name: str) -> str:
    """Endpoint path for a logical call, per platform version."""
    if version == "v3":
        return {
            "upload": "/files",
            "create": "/generation/image-to-model",
            "task": "/tasks/{task_id}",
            "balance": "/account/balance",
        }[name]
    return {
        "upload": "/upload",
        "create": "/task",
        "task": "/task/{task_id}",
        "balance": "/user/balance",
    }[name]


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


def _load_keys_from_file() -> List[str]:
    """Every Tripo token found in the key file, in file order.

    The first entry is the primary key; the rest are fallbacks. Tripo keys
    expire or run out of credit independently, so one key must never be the
    only reason the whole 3D chain is unavailable.
    """
    if not os.path.isfile(_KEYFILE):
        return []
    try:
        with open(_KEYFILE, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return []
    keys: List[str] = []

    def _add(token: str) -> None:
        if token and token not in keys:
            keys.append(token)

    # An explicit tripo marker wins the first slot.
    for line in txt.splitlines():
        low = line.lower()
        if "tripo" in low and ("tsk_" in line):
            m = re.search(r"tsk_[A-Za-z0-9_-]+", line)
            if m:
                _add(m.group(0))
                break
    # Then any other tsk_ token in the file, in order.
    for m in re.finditer(r"tsk_[A-Za-z0-9_-]{8,}", txt):
        _add(m.group(0))
    return keys


API_KEYS: List[str] = []
if API_KEY:
    API_KEYS.append(API_KEY)
for _k in _load_keys_from_file():
    if _k not in API_KEYS:
        API_KEYS.append(_k)
if not API_KEY:
    API_KEY = API_KEYS[0] if API_KEYS else ""

_active_key_index = 0


def _current_key() -> str:
    if not API_KEYS:
        return API_KEY
    return API_KEYS[_active_key_index % len(API_KEYS)]


def _rotate_key() -> str:
    """Move to the next configured key and return it."""
    global _active_key_index, API_KEY
    if len(API_KEYS) > 1:
        _active_key_index = (_active_key_index + 1) % len(API_KEYS)
        API_KEY = API_KEYS[_active_key_index]
        print(f"[tripo] switching to fallback key {API_KEY[:14]}...", flush=True)
    return _current_key()


# ---------------------------------------------------------------------------
# HTTP helpers (use stdlib so no extra deps required)
# ---------------------------------------------------------------------------
#
# A blocked or offline provider must not cost the user a minute of waiting
# for every attempt. The first connection error puts the provider on a short
# cooldown: later calls fail immediately with a readable message until a
# probe succeeds again. The cooldown is tracked per host: the CN platform
# and the global one live in different networks, so one of them being
# blocked must not silence the other.
_UNREACHABLE_UNTIL: Dict[str, float] = {}
_UNREACHABLE_COOLDOWN = 120.0


def provider_unreachable(base: Optional[str] = None) -> bool:
    """True while the provider is known to be unreachable."""
    return time.time() < _UNREACHABLE_UNTIL.get(base or BASE, 0.0)


def _mark_unreachable(base: str) -> None:
    _UNREACHABLE_UNTIL[base] = time.time() + _UNREACHABLE_COOLDOWN


def _mark_reachable(base: str) -> None:
    _UNREACHABLE_UNTIL.pop(base, None)


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


def _request(method: str, path_key: str, *, path_args: Optional[Dict[str, Any]] = None,
             body: Optional[bytes] = None,
             headers: Optional[Dict[str, str]] = None,
             timeout: float = 60.0, retries: int = 2, backoff: float = 1.5,
             body_for=None) -> Dict[str, Any]:
    """HTTP wrapper with retry+backoff for transient failures.

    Retries up to `retries` times on connection errors and HTTP 5xx.
    HTTP 4xx is not retried (caller asked for something invalid).
    Each attempt has `timeout` seconds; backoff doubles from `backoff`s.

    `path_key` names a logical endpoint ("upload", "create", "task",
    "balance"); every platform version maps it to its own path. A rejected
    key (401) or a missing endpoint (404) moves on to the next
    platform/key candidate without burning one of the caller's retries.
    """
    h = {}
    if headers:
        h.update(headers)
    last_err = None
    attempt = 0
    # Candidate list = every (platform version, key) pair.  The order is
    # worked out here and not taken from the shared "active key" index: the
    # background balance probe rotates that index too, and a request that
    # rotated into the key another thread had just parked would keep using
    # the dead one.
    keys = [_current_key()]
    for key in API_KEYS:
        if key not in keys:
            keys.append(key)
    versions = ["v3", "v2"] if _api_version == "v3" else ["v2", "v3"]
    candidates = [(v, k) for v in versions for k in keys]
    tried = 0
    while attempt <= retries:
        version, key = candidates[min(tried, len(candidates) - 1)]
        base = _base_for(version)
        if provider_unreachable(base):
            # This host is on cooldown — move on instead of waiting for it.
            if tried + 1 < len(candidates):
                tried += 1
                continue
            raise RuntimeError(
                "Tripo 当前网络不可达（刚刚连接失败），请检查网络或改用其他引擎"
            )
        url = base + _path(version, path_key).format(**(path_args or {}))
        payload = body_for(version) if body_for is not None else body
        h["Authorization"] = "Bearer " + key
        req = urllib.request.Request(url, data=payload, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "ignore")
            _mark_reachable(base)
            # This platform accepted the key: remember it for the next call.
            _set_version(version)
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
        except urllib.error.HTTPError as e:
            try:
                err = e.read().decode("utf-8", "ignore")
            except Exception:
                err = str(e.reason)
            # A key the host does not accept (401), or an endpoint the host
            # does not have (404 — the two platforms use different paths),
            # is recoverable: move to the next platform/key candidate.
            # Switching must not consume one of the caller's retries.
            if e.code in (401, 404) and tried + 1 < len(candidates):
                tried += 1
                nxt_v, nxt_k = candidates[tried]
                print(
                    f"[tripo] {version} rejected the key (HTTP {e.code}), "
                    f"trying {nxt_v}/{nxt_k[:14]}...",
                    flush=True,
                )
                continue
            if 400 <= e.code < 500:
                raise RuntimeError(f"Tripo HTTP {e.code} on {method} {path_key}: {err[:400]}")
            last_err = RuntimeError(f"Tripo HTTP {e.code} on {method} {path_key}: {err[:200]}")
            print(f"[tripo] attempt {attempt+1}/{retries+1} got {e.code}, retrying in {backoff:.1f}s", flush=True)
        except Exception as e:
            last_err = RuntimeError(f"Tripo {method} {path_key} failed: {e}")
            if _is_connection_failure(e):
                _mark_unreachable(base)
            print(f"[tripo] attempt {attempt+1}/{retries+1} {type(e).__name__}: {str(e)[:160]}", flush=True)
            if provider_unreachable(base):
                break
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
        attempt += 1
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
        j = _request("GET", "balance", timeout=timeout, retries=retries)
        if j.get("code", 0) != 0:
            return {"ok": False, "error": j.get("message") or j.get("msg") or str(j)}
        data = j.get("data") or {}
        balance = data.get("balance", 0)
        frozen = data.get("frozen", 0)
        return {
            "ok": True,
            "balance": int(float(balance or 0)),
            "frozen": int(float(frozen or 0)),
            "total": int(float(balance or 0)) + int(float(frozen or 0)),
            "platform": _api_version,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def health() -> Dict[str, Any]:
    return {
        "key_loaded": bool(API_KEY),
        "key_preview": (API_KEY[:14] + "...") if API_KEY else None,
        "key_count": len(API_KEYS),
        "base": BASE,
        "platform": _api_version,
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
    j = _request("POST", "upload", body=body, headers={"Content-Type": ctype}, timeout=25.0, retries=1)
    code = (j.get("code") if isinstance(j, dict) else None)
    data = j.get("data") if isinstance(j, dict) else None
    if code not in (None, 0):
        raise RuntimeError(
            f"Tripo upload non-zero code={code}: "
            f"{j.get('message') or j.get('msg') or j}"
        )
    token = None
    if isinstance(data, dict):
        token = data.get("file_token") or data.get("image_token")
    if not token:
        # older shape
        token = j.get("image_token")
    if not token:
        raise RuntimeError(f"Tripo upload returned no file token: {j}")
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
    def _body_for(version: str) -> bytes:
        if version == "v3":
            body3: Dict[str, Any] = {
                "input": image_token,
                "model": model_version,
                "texture": texture,
                "pbr": pbr,
                "texture_quality": texture_quality,
                "quad": quad,
                "auto_size": auto_size,
            }
            if face_limit:
                body3["face_limit"] = face_limit
            return json.dumps(body3).encode("utf-8")
        body2: Dict[str, Any] = {
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
            body2["face_limit"] = face_limit
        return json.dumps(body2).encode("utf-8")

    j = _request("POST", "create", body_for=_body_for,
                 headers={"Content-Type": "application/json"}, timeout=60.0)
    code = j.get("code", 0)
    if code != 0:
        raise RuntimeError(
            f"Tripo create task failed code={code}: "
            f"{j.get('message') or j.get('msg') or j}"
        )
    payload = j.get("data") or {}
    tid = payload.get("task_id")
    if not tid:
        raise RuntimeError(f"Tripo create task returned no task_id: {j}")
    return tid


def get_task(task_id: str) -> Dict[str, Any]:
    j = _request("GET", "task", path_args={"task_id": task_id}, timeout=30.0)
    if j.get("code", 0) != 0:
        raise RuntimeError(
            f"Tripo get_task failed: {j.get('message') or j.get('msg') or j}"
        )
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
        # v3 returns a single PBR model url
        ("model_url", "model_pbr.glb"),
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
def _height_scale(mesh, target_height_mm: float = 70.0) -> float:
    """Factor that turns the model's standing height into the target height."""
    ext = mesh.extents
    if len(ext) < 3:
        return 0.0
    height = float(ext[2])
    target = float(target_height_mm or 0)
    if target > 0 and height > 0:
        return target / height
    largest = float(max(ext))
    if largest <= 0:
        return 0.0
    return 100.0 / largest


def _place_on_bed(mesh) -> Any:
    """Move the model so its lowest point sits exactly on z=0."""
    bounds = mesh.bounds
    if float(bounds[0][2]) < 0:
        mesh.apply_translation([0, 0, -float(bounds[0][2])])
    return mesh


def _build_body(mesh) -> Any:
    """Turn the cloud model into one solid body for the slicer.

    Tripo hands the model back standing along Y and, like the other cloud
    engines, as a set of separate shells.  The old cleanup kept the shell
    with the most triangles and dropped everything else, so a figure that
    came back as head, body, arms and a base ended up as one of them.

    The shells overlap each other and none of them is watertight on its
    own, so the printable body is rebuilt from their volume: one closed
    surface the slicer can cut.
    """
    import mesh_postprocess
    solid = mesh_postprocess.solidify_mesh(mesh, pitch_mm=0.5)
    if not len(solid.faces):
        # The voxel pass failed - fall back to the shells themselves, closed
        # up as well as the geometry allows.
        solid = mesh_postprocess.seal_for_print(mesh)
    return solid


def _build_viewer(mesh) -> Any:
    """The browser model: the painted shells, decimated for a fast preview.

    It is the same figurine the slicer receives, only lighter: the shells
    keep the paint and the detail the cloud engine gave us, while the
    printable copy is the merged solid body.
    """
    import mesh_postprocess
    return mesh_postprocess.optimize_for_web(mesh, target_faces=120000, texture_size=2048)


def _prepare_source(mesh) -> Any:
    """Bring a raw cloud model into the print scale and clean it up.

    Works on a copy: the caller needs the same source twice, once for the
    painted preview and once for the printable body.
    """
    import mesh_postprocess
    mesh = mesh.copy()
    # Tripo's model stands along Y; the print bed wants Z.
    mesh = mesh_postprocess.align_up_axis(mesh, source_up="y")
    # The cloud model arrives in its own units (about a metre tall).  The
    # voxel pass that rebuilds a solid body works in millimetres, so the
    # model is brought to the print scale first - otherwise the grid is
    # smaller than the model and the result degenerates into a box.
    largest = float(max(mesh.extents))
    if largest > 0:
        mesh.apply_scale(mesh_postprocess.PRINT_LENGTH_MM / largest)
    # Drop the loose fragments, keep every real body of the figurine.
    mesh = mesh_postprocess.keep_significant_shells(mesh)
    # Only merge vertices that really are the same point *and* carry the
    # same texture coordinates.  trimesh's merge_tex=True welds vertices
    # regardless of their UVs, which closes the texture seams: the two
    # copies of a seam vertex end up with one UV and the triangles on the
    # other side stretch across the whole atlas, which is what paints the
    # white cracks over the model.
    mesh.merge_vertices(merge_tex=False)
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
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
    # The browser model and the print model are the same figurine at the
    # same size, so the preview can never show something different from
    # what gets printed.
    prepared = _prepare_source(mesh)
    viewer = _build_viewer(prepared.copy())
    printable = _build_body(prepared)
    # One scale for both, taken from the printable body: the preview must
    # show the model at exactly the size that goes to the printer.
    scale = _height_scale(printable, target_height_mm)
    if scale > 0:
        printable.apply_scale(scale)
        viewer.apply_scale(scale)
    printable = _place_on_bed(printable)
    viewer = _place_on_bed(viewer)
    # The printable copy carries geometry only: the STL/OBJ formats have no
    # room for a texture anyway.

    paths: Dict[str, str] = {}
    stl_path = os.path.join(out_dir, "mesh.stl")
    obj_path = os.path.join(out_dir, "mesh.obj")
    import mesh_postprocess
    mesh_postprocess.export_atomic(printable, stl_path)
    paths["stl"] = stl_path
    mesh_postprocess.export_atomic(printable, obj_path)
    paths["obj"] = obj_path

    # GLB keeps visual (PBR textures) — viewers in the browser use this
    if keep_visual:
        glb_path = os.path.join(out_dir, "mesh.glb")
        try:
            mesh_postprocess.export_atomic(viewer, glb_path)
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

