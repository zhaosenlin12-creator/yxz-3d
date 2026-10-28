"""FastAPI backend for Cartoon Print Studio (AI 思考模式)."""
import os, time, uuid, base64, traceback, threading, json, re
import shutil
from pathlib import Path
from urllib.parse import quote
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
# Resolve paths: env override (packaged mode) > sibling of backend/ (source mode)
_ROOT = (
    os.environ.get("CARTOON_ROOT")
    or (os.path.dirname(os.environ["CARTOON_FRONTEND_DIR"]) if os.environ.get("CARTOON_FRONTEND_DIR") else None)
)
if not _ROOT:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = _ROOT
FRONTEND = os.environ.get("CARTOON_FRONTEND_DIR") or os.path.join(ROOT, "frontend")
DATA = os.environ.get("CARTOON_DATA_DIR") or os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)
_BACKEND = os.path.join(ROOT, "backend")
import sys
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
import sd_client, triposr_runner, bambu, llm_client, api_image, hunyuan_runner, mesh_postprocess, tripo_api, scene_jobs
import software_integrations
import progress
import project_store
import laser_card
import edge_tts_api
SCENE_STORE = scene_jobs.SceneJobStore(DATA)
PROJECT_STORE = project_store.ProjectStore(DATA)
app = FastAPI(title="Cartoon Print Studio API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

EXT_MIME = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".obj": "text/plain",
    ".stl": "model/stl",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    # The laser cut file is an SVG: the laser software and the browser both
    # need it to be served as an image, not as an opaque download.
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".ply": "application/octet-stream",
    ".splat": "application/octet-stream",
    ".sog": "application/octet-stream",
    ".spz": "application/octet-stream",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

# The one-time Y-up -> Z-up migration in /api/demo only ever applied to the
# old local Hunyuan demos. Fresh high-resolution exports are far bigger and
# need no migration, so cap the size we are willing to re-export.
DEMO_UPGRADE_MAX_BYTES = 16 * 1024 * 1024


async def _save_uploaded_file(upload: UploadFile, target: str, max_bytes: int) -> int:
    """Stream an upload to disk with a hard size limit."""
    written = 0
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, "wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, f"文件超过 {max_bytes // (1024 * 1024)}MB 限制")
                handle.write(chunk)
    except Exception:
        if os.path.isfile(target):
            os.remove(target)
        raise
    finally:
        await upload.close()
    return written
def _save_preview_items(raw_items, pdir, captions, sub_prompts, sid, req_n, pg):
    """Save preview PNGs to disk, skipping any None entries.

    Returns (items, n_saved, n_failed). Caller decides how to report
    failures to the frontend (typically via a progress event).
    """
    items = []
    n_failed = 0
    n_saved = 0
    for i, entry in enumerate(raw_items[:req_n]):
        blob, tag = entry
        if blob is None:
            n_failed += 1
            pg.emit(f"preview-skip-{i}", 90, f"第 {i+1} 张生成失败,跳过")
            continue
        path_i = os.path.join(pdir, f"img_{i}.png")
        with open(path_i, "wb") as f:
            f.write(blob)
        b64 = base64.b64encode(blob).decode()
        items.append({
            "index": i,
            "b64": b64,
            "path": f"/api/data/{sid}/previews/img_{i}.png",
            "caption": captions[i] if i < len(captions) else f"图 {i+1}",
            "sub_prompt": sub_prompts[i] if i < len(sub_prompts) else "",
            "tag": tag,
        })
        n_saved += 1
    return items, n_saved, n_failed


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def session_dir(sid: str) -> str:
    """Resolve a session folder inside the data directory.

    The id comes from the client, so it is validated before it is joined to
    the data root: a session id may never point outside ``data/``.
    """
    if not SESSION_ID_RE.fullmatch(sid or ""):
        raise HTTPException(400, "无效的会话 ID")
    p = os.path.join(DATA, sid)
    if os.path.commonpath([os.path.abspath(p), os.path.abspath(DATA)]) != os.path.abspath(DATA):
        raise HTTPException(400, "无效的会话 ID")
    os.makedirs(p, exist_ok=True)
    return p


@app.post("/api/upload-image", status_code=201)
async def upload_image(image: UploadFile = File(...), source: str = Form("camera")):
    """Accept a camera / picker image, keep it as the session preview and describe it.

    The picture is stored as ``previews/img_0.png`` inside a fresh session so
    the existing preview -> 3D pipeline can reuse it directly. The returned
    description pre-fills the chat input; when no vision provider answers the
    caller still gets a usable factual description.
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(415, "只支持上传图片文件")

    sid = uuid.uuid4().hex[:12]
    previews = os.path.join(session_dir(sid), "previews")
    os.makedirs(previews, exist_ok=True)

    img_path = os.path.join(previews, "img_0.png")
    size = await _save_uploaded_file(image, img_path, 15 * 1024 * 1024)

    try:
        from PIL import Image as PILImage
        with PILImage.open(img_path) as decoded:
            decoded.load()
            if max(decoded.size) > 4096:
                raise HTTPException(413, "图片尺寸过大，请使用 4096x4096 以下的图片")
            if decoded.mode not in ("RGBA", "RGB"):
                decoded = decoded.convert("RGBA")
            decoded.save(img_path, "PNG")
            width, height = decoded.size
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"图片无法读取：{exc}") from exc

    description = ""
    try:
        with open(img_path, "rb") as handle:
            img_base64 = base64.b64encode(handle.read()).decode()
        vision_prompt = (
            "请用一句话描述这张图片的主要内容，重点说明适合制作什么样的创意作品，控制在20字以内。"
        )
        reply = llm_client.vision_chat(vision_prompt, img_base64)
        if reply:
            description = reply.strip()
    except Exception as vision_err:
        print(f"[upload-image] vision analysis failed: {vision_err}")
    if not description:
        description = f"一张 {width}x{height} 的照片"

    with open(os.path.join(DATA, sid, "_source.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "source": source,
            "created_at": int(time.time()),
            "width": width,
            "height": height,
            "size_bytes": size,
        }, handle, ensure_ascii=False)

    return {
        "session_id": sid,
        "image_path": f"/api/data/{sid}/previews/img_0.png",
        "description": description,
        "width": width,
        "height": height,
        "message": "照片已上传成功",
    }


class SessionForkReq(BaseModel):
    image_index: int = Field(default=0, ge=0, le=9)


@app.post("/api/projects/{project_id}/media", status_code=201)
async def upload_project_media(project_id: str, image: UploadFile = File(...)):
    try:
        project_path = PROJECT_STORE._path(project_id)
    except project_store.ProjectValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not project_path.is_file():
        raise HTTPException(404, "project not found")
    media_dir = PROJECT_STORE.root / project_id / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    temporary = media_dir / f".upload-{uuid.uuid4().hex}.tmp"
    try:
        await _save_uploaded_file(image, str(temporary), 15 * 1024 * 1024)
        from PIL import Image
        with Image.open(temporary) as decoded:
            image_format = (decoded.format or "").upper()
            width, height = decoded.size
            decoded.verify()
        if image_format not in {"PNG", "JPEG", "WEBP"} or width > 12000 or height > 12000:
            raise HTTPException(415, "仅支持小于 12000 × 12000 的 PNG、JPEG 或 WebP 图片")
        extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image_format]
        filename = f"{uuid.uuid4().hex}.{extension}"
        os.replace(temporary, media_dir / filename)
        return {"path": f"/api/projects/{project_id}/media/{filename}", "width": width, "height": height}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(415, f"图片无法读取：{exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
        await image.close()


@app.get("/api/projects/{project_id}/media/{filename}")
def read_project_media(project_id: str, filename: str):
    try:
        project_path = PROJECT_STORE._path(project_id)
    except project_store.ProjectValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not project_path.is_file() or not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|webp)", filename):
        raise HTTPException(404, "project image not found")
    candidate = (PROJECT_STORE.root / project_id / "media" / filename).resolve()
    if not candidate.is_file():
        raise HTTPException(404, "project image not found")
    media_type = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[filename.rsplit(".", 1)[1]]
    return FileResponse(candidate, media_type=media_type)


def _safe_session_path(sid: str) -> Path:
    if not sid or not sid.isascii() or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in sid):
        raise HTTPException(400, "invalid session id")
    path = (Path(DATA) / sid).resolve()
    if not path.is_relative_to(Path(DATA).resolve()):
        raise HTTPException(400, "invalid session id")
    return path


@app.post("/api/session/{sid}/fork", status_code=201)
def fork_session(sid: str, req: SessionForkReq):
    source = _safe_session_path(sid)
    if not source.is_dir():
        raise HTTPException(404, "source session not found")
    source_previews = source / "previews"
    if not source_previews.is_dir():
        raise HTTPException(404, "source previews are not ready")
    available = [
        item for item in source_previews.glob(f"img_{req.image_index}.*")
        if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    if not available:
        raise HTTPException(404, "selected preview is not ready")

    new_sid = uuid.uuid4().hex[:12]
    target = Path(DATA) / new_sid
    (target / "previews").mkdir(parents=True, exist_ok=False)
    try:
        for preview in source_previews.iterdir():
            if preview.is_file() and preview.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                shutil.copy2(preview, target / "previews" / preview.name)
        for name in ("prompt.txt", "specs.json"):
            artifact = source / name
            if artifact.is_file():
                shutil.copy2(artifact, target / name)
        (target / "_source.json").write_text(json.dumps({
            "source_session_id": sid,
            "image_index": req.image_index,
            "created_at": int(time.time()),
        }, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(500, f"could not create model version: {exc}") from exc
    return {
        "session_id": new_sid,
        "source_session_id": sid,
        "image_index": req.image_index,
        "preview_url": f"/api/data/{new_sid}/previews/{available[0].name}",
    }


@app.put("/api/session/{sid}/edited-model")
async def save_edited_model(
    sid: str,
    stl: UploadFile = File(...),
    obj: UploadFile = File(...),
    glb: UploadFile = File(...),
):
    session = _safe_session_path(sid)
    model_dir = session / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = model_dir / f".edited-{uuid.uuid4().hex}"
    temporary_dir.mkdir()
    targets = {"stl": temporary_dir / "mesh.stl", "obj": temporary_dir / "mesh.obj", "glb": temporary_dir / "mesh.glb"}
    try:
        await _save_uploaded_file(stl, str(targets["stl"]), 100 * 1024 * 1024)
        await _save_uploaded_file(obj, str(targets["obj"]), 100 * 1024 * 1024)
        await _save_uploaded_file(glb, str(targets["glb"]), 100 * 1024 * 1024)
        stl_bytes = targets["stl"].read_bytes()
        obj_text = targets["obj"].read_text(encoding="utf-8", errors="replace")
        glb_bytes = targets["glb"].read_bytes()
        if not stl_bytes or not glb_bytes.startswith(b"glTF"):
            raise HTTPException(422, "导出的 STL 或 GLB 文件无效")
        if "v " not in obj_text or "f " not in obj_text:
            raise HTTPException(422, "导出的 OBJ 缺少顶点或三角面")
        try:
            import trimesh
            mesh = trimesh.load(targets["stl"], force="mesh")
            if not len(mesh.faces) or not len(mesh.vertices) or not all(map(lambda value: value == value and abs(value) < 1e7, mesh.extents)):
                raise ValueError("STL 网格为空或尺寸无效")
        except Exception as exc:
            raise HTTPException(422, f"STL 网格验证失败：{exc}") from exc
        for fmt, destination in (("stl", model_dir / "mesh.stl"), ("obj", model_dir / "mesh.obj"), ("glb", model_dir / "mesh.glb")):
            os.replace(targets[fmt], destination)
        return {
            "ok": True,
            "session_id": sid,
            "faces": int(len(mesh.faces)),
            "extents_mm": [round(float(value), 2) for value in mesh.extents.tolist()],
        }
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


class PreviewsReq(BaseModel):
    prompt: str
    n: int = 4
    seed: int = 42
    prefer: str = "aixj"   # aixj (gpt-image) -> minimax -> jojo -> local
    session_id: str = ""

class RefineReq(BaseModel):
    """按批注修改一版：把带批注的预览图 + 指令发给 AI 图片编辑模型。"""
    session_id: str
    instruction: str = Field(min_length=1, max_length=1000)
    image_index: int = 0
    # Optional data URL / base64 PNG of the annotated canvas. When present it is
    # used as the edit reference; otherwise the stored preview img_N is used.
    image: Optional[str] = None

class ThreeDReq(BaseModel):
    session_id: str
    image_index: int = 0
class PrintReq(BaseModel):
    session_id: str
    seed: Optional[int] = None   # when picking a candidate from /api/3d_multi


class PromptPolishReq(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


def _project_or_422(operation):
    try:
        return operation()
    except project_store.ProjectValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/prompt/polish")
def polish_prompt(req: PromptPolishReq):
    original = req.text.strip()
    if not original:
        raise HTTPException(422, "提示词不能为空")
    local = llm_client.polish_prompt_local(original)
    if not llm_client.has_provider():
        return {
            "ok": False,
            "text": original,
            "reason": "provider_not_configured",
            "fallback": {"text": local, "source": "local_rules"},
        }
    try:
        reply, _provider = llm_client.llm_call(
            "请优化以下用于生成单个、适合 3D 打印的卡通模型的提示词。保留用户的主体、颜色和明确要求，"
            "补足形态、姿势、材质与纯色背景描述。只返回 JSON："
            '{"suggestion":"润色后的提示词"}。原文：' + json.dumps(original, ensure_ascii=False),
            timeout=8,
            # The UI waits on this request; an unreachable provider must not
            # hold the button disabled for longer than the user tolerates.
            deadline=time.time() + 8,
        )
        if not reply:
            raise ValueError("provider returned no suggestion")
        suggestion = reply.strip().strip("`").strip()
        if suggestion.startswith("json"):
            suggestion = suggestion[4:].strip()
        try:
            parsed = json.loads(suggestion)
            if isinstance(parsed, dict):
                suggestion = parsed.get("suggestion") or parsed.get("text") or ""
        except json.JSONDecodeError:
            pass
        suggestion = str(suggestion).strip().strip('"')
        if not suggestion or len(suggestion) > 20_000:
            raise ValueError("provider returned an invalid suggestion")
        return {"ok": True, "text": original, "suggestion": suggestion}
    except Exception:
        return {
            "ok": False,
            "text": original,
            "reason": "provider_unavailable",
            "fallback": {"text": local, "source": "local_rules"},
        }


@app.get("/api/projects")
def list_projects():
    return {"projects": PROJECT_STORE.list()}


@app.post("/api/projects", status_code=201)
def create_project(payload: Dict[str, Any]):
    return _project_or_422(lambda: PROJECT_STORE.create(payload))


@app.get("/api/projects/{project_id}")
def read_project(project_id: str):
    project = _project_or_422(lambda: PROJECT_STORE.read(project_id))
    if project is None:
        raise HTTPException(404, "project not found")
    return project


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, payload: Dict[str, Any]):
    project = _project_or_422(lambda: PROJECT_STORE.update(project_id, payload))
    if project is None:
        raise HTTPException(404, "project not found")
    return project


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    deleted = _project_or_422(lambda: PROJECT_STORE.delete(project_id))
    if not deleted:
        raise HTTPException(404, "project not found")
class ThinkReq(BaseModel):
    prompt: str
    n: int = 6
class PreviewsV2Req(BaseModel):
    prompt: str
    n: int = 4
    seed: int = 42
    prefer: str = "aixj"   # aixj (gpt-image) -> minimax -> jojo -> local
    session_id: str = ""
class ThreeDMultiReq(BaseModel):
    session_id: str
    image_index: int = 0
    seeds: List[int] = [42, 137, 2024]
_BALANCE_CACHE = {"value": None, "ts": 0.0}
_BALANCE_TTL = 60.0  # cache for 60s
_BALANCE_PROBE = {"running": False}
_BALANCE_PROBE_LOCK = threading.Lock()


def _refresh_balance_background() -> None:
    """Probe the Tripo balance off the request path.

    The UI polls /api/health on every page load. Waiting for an unreachable
    provider here would add seconds to every first paint, so the probe runs
    in the background and the cached answer is served immediately.
    """
    with _BALANCE_PROBE_LOCK:
        if _BALANCE_PROBE["running"]:
            return
        _BALANCE_PROBE["running"] = True

    def worker():
        try:
            bal = tripo_api.get_balance(timeout=4.0, retries=0)
        except Exception as exc:
            bal = {"ok": False, "error": str(exc)}
        finally:
            _BALANCE_CACHE["value"] = bal
            _BALANCE_CACHE["ts"] = time.time()
            with _BALANCE_PROBE_LOCK:
                _BALANCE_PROBE["running"] = False

    threading.Thread(target=worker, daemon=True).start()


def _cached_tripo_balance():
    """Return only a fresh cached balance and refresh stale data in background."""
    if time.time() - _BALANCE_CACHE["ts"] > _BALANCE_TTL:
        _refresh_balance_background()
        return None
    return _BALANCE_CACHE["value"]

@app.get("/api/health")
def health():
    tripo_info = tripo_api.health()
    bal = _BALANCE_CACHE["value"]
    if bal is None or (time.time() - _BALANCE_CACHE["ts"]) > _BALANCE_TTL:
        _refresh_balance_background()
    return {"ok": True, "ts": time.time(),
            "jojo_key_loaded": api_image.JOJO_KEY != "",
            "jojo_total_keys": len(api_image.JOJO_KEYS),
            "jojo_dead_keys": len(api_image._JOJO_DEAD_KEYS),
            "jojo_alive_keys": max(0, len(api_image.JOJO_KEYS) - len(api_image._JOJO_DEAD_KEYS)),
            "llm_keys": sum(llm_client.key_counts().values()),
            "llm_detail": llm_client.key_counts(),
            "aixj_image_keys": len(api_image.AIXJ_IMAGE_KEYS),
            "minimax_image_keys": len(api_image.MINIMAX_IMAGE_KEYS),
            "prefer_chain": (api_image.health() or {}).get("chain", "?"),
            "tripo3d_key_loaded": tripo_info.get("key_loaded", False),
            "tripo3d_balance": (bal or {}).get("balance"),
            "tripo3d_ok": (bal or {}).get("ok", False),
            # True while the first probe is still running: the UI shows
            # "checking" instead of wrongly reporting the provider as down.
            "tripo3d_checking": bool(_BALANCE_PROBE["running"])}


class EdgeTtsReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    volume: Optional[str] = None


@app.get("/api/tts/edge/voices")
async def edge_tts_voices():
    """The free Microsoft Edge neural voices 宜小智 can fall back to."""
    try:
        voices = await edge_tts_api.list_voices()
    except Exception as exc:
        raise HTTPException(503, str(exc))
    return {"ok": True, "voices": voices}


@app.post("/api/tts/edge")
async def edge_tts_speak(req: EdgeTtsReq):
    """Render a line of speech with an Edge neural voice (free, no key)."""
    try:
        audio = await edge_tts_api.synthesize(
            req.text,
            voice=req.voice,
            rate=req.rate or edge_tts_api.DEFAULT_RATE,
            pitch=req.pitch or edge_tts_api.DEFAULT_PITCH,
            volume=req.volume or edge_tts_api.DEFAULT_VOLUME,
        )
    except Exception as exc:
        raise HTTPException(503, f"Edge 语音包合成失败：{exc}")
    return Response(content=audio, media_type="audio/mpeg")

@app.get("/api/demo")
def demo_model():
    """Return a bundled local model for the zero-wait first experience.

    The demo is discovered from the local data directory so packaged installs
    do not need to hard-code a session id. It never calls an external provider.
    """
    candidates = []
    bundled_demo = os.path.join(DATA, "demo")
    if os.path.isfile(os.path.join(bundled_demo, "model", "mesh.glb")):
        bundled_prompt = "一个蓝色卡通小英雄，橙色披风，圆润可爱"
        try:
            with open(os.path.join(bundled_demo, "demo.json"), "r", encoding="utf-8-sig") as handle:
                bundled_prompt = json.load(handle).get("prompt") or bundled_prompt
        except (OSError, ValueError, AttributeError):
            pass
        candidates.append({
            "session_id": "demo",
            "model_url": "/api/data/demo/model/mesh.glb",
            "preview_url": "/api/data/demo/previews/img_0.png"
            if os.path.isfile(os.path.join(bundled_demo, "previews", "img_0.png")) else None,
            "prompt": bundled_prompt,
            "updated_at": 1e100,
            "bundled": True,
        })
    try:
        for sid in os.listdir(DATA):
            # Scratch directories (leading "_") hold throw-away verification
            # files, never user work. Offering one as "the demo model" is
            # both wrong and, for the big test meshes, extremely slow.
            if sid.startswith("_"):
                continue
            model_path = os.path.join(DATA, sid, "model", "mesh.glb")
            if not os.path.isfile(model_path):
                continue
            preview_dir = os.path.join(DATA, sid, "previews")
            previews = sorted(
                name for name in os.listdir(preview_dir)
                if name.lower().endswith((".png", ".jpg", ".jpeg"))
            ) if os.path.isdir(preview_dir) else []
            candidates.append({
                "session_id": sid,
                "model_url": f"/api/data/{sid}/model/mesh.glb",
                "preview_url": f"/api/data/{sid}/previews/{previews[0]}" if previews else None,
                "prompt": "一个蓝色卡通小英雄，橙色披风，圆润可爱",
                "updated_at": os.path.getmtime(model_path),
            })
    except OSError as exc:
        raise HTTPException(500, f"demo discovery failed: {exc}")
    if not candidates:
        raise HTTPException(404, "no local demo model")
    candidates.sort(key=lambda item: item["updated_at"], reverse=True)
    result = candidates[0]
    # Older local Hunyuan demos were stored Y-up while the print base was
    # generated Z-up. Upgrade once so the browser no longer shows that base
    # as a tall board behind the character, and keep the STL/OBJ in sync.
    if result.pop("bundled", False):
        result.pop("updated_at", None)
        return result
    model_path = os.path.join(DATA, result["session_id"], "model", "mesh.glb")
    marker_path = os.path.join(os.path.dirname(model_path), "demo_ready.json")
    try:
        # Re-exporting a 500k-triangle mesh takes seconds. Remember that the
        # upgrade already ran so the "try a model now" button stays instant.
        signature = {"size": os.path.getsize(model_path), "mtime": os.path.getmtime(model_path)}
        already_prepared = False
        if os.path.isfile(marker_path):
            try:
                with open(marker_path, "r", encoding="utf-8") as handle:
                    already_prepared = json.load(handle) == signature
            except Exception:
                already_prepared = False
        # The Y-up migration exists for the old local Hunyuan demos (a few MB).
        # A fresh high-resolution export is tens of megabytes and needs no
        # migration: the web viewer already auto-detects the up axis. Running
        # trimesh over such a mesh turned this endpoint into a 30s+ hang, so
        # oversized models are served as-is.
        upgrade_allowed = signature["size"] <= DEMO_UPGRADE_MAX_BYTES
        if not already_prepared and upgrade_allowed:
            import trimesh
            legacy_mesh = trimesh.load(model_path, force="mesh")
            if mesh_postprocess.has_legacy_y_up_base(legacy_mesh):
                cleaned = mesh_postprocess.upgrade_legacy_y_up_mesh(legacy_mesh)
                model_dir = os.path.dirname(model_path)
                mesh_postprocess.export_view_glb(cleaned, model_path)
                cleaned.export(os.path.join(model_dir, "mesh.obj"))
                cleaned.export(os.path.join(model_dir, "mesh.stl"))
            elif mesh_postprocess.component_count(legacy_mesh) > 1:
                # Keep old bundled demos compatible with the explode-view UI.
                mesh_postprocess.export_view_glb(legacy_mesh, model_path)
        if not already_prepared:
            signature = {"size": os.path.getsize(model_path), "mtime": os.path.getmtime(model_path)}
            try:
                with open(marker_path, "w", encoding="utf-8") as handle:
                    json.dump(signature, handle)
            except OSError:
                pass
    except Exception as exc:
        print(f"[demo] orientation upgrade skipped: {exc}", flush=True)
    result.pop("updated_at", None)
    return result

@app.get("/api/engines")
def engines():
    """Report local/cloud model availability so the UI can choose safely."""
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        gpu = torch.cuda.get_device_name(0) if cuda else None
    except Exception:
        cuda, gpu = False, None
    vram_mb = _detect_vram_mb()
    hunyuan_status = hunyuan_runner.get_status()
    return {
        "cuda": cuda,
        "gpu": gpu,
        "vramMb": vram_mb,
        "engines": [
            {
                "id": "hunyuan",
                "available": bool(hunyuan_status.get("available")),
                "ready": bool(hunyuan_status.get("ready")),
                "local": True,
                "label": "Hunyuan3D-2 mini",
                "quality": "高",
                "cost": "本地免费",
                "note": "首次加载较慢，后续复用模型" if hunyuan_status.get("available") else hunyuan_status.get("reason", "当前不可用"),
            },
            {
                "id": "multi",
                "available": bool(triposr_runner.is_available()),
                "local": True,
                "label": "TripoSR 多视角",
                "quality": "中高",
                "cost": "本地免费",
                "note": "适合快速试错，卡通形状稳定性一般",
            },
            {
                "id": "cartoon",
                "available": True,
                "local": True,
                "label": "卡通浮雕",
                "quality": "打印稳定",
                "cost": "本地免费",
                "note": "最快的离线兜底路径",
            },
            {
                # Stable Fast 3D reconstructs a whole object in about a
                # second, but it only fits on a card with enough memory.
                "id": "sf3d",
                "available": False,
                "local": True,
                "label": "Stable Fast 3D",
                "quality": "很高（带贴图）",
                "cost": "本地免费",
                "requiresVramMb": 10_000,
                "note": _engine_note(
                    "Stable Fast 3D",
                    vram_mb,
                    10_000,
                    "权重未安装，或显存不足 10 GB",
                ),
            },
            {
                # Hunyuan3D-2.1 is the high-resolution sibling of the mini
                # model that already runs here.
                "id": "hunyuan21",
                "available": False,
                "local": True,
                "label": "Hunyuan3D-2.1",
                "quality": "最高（高模）",
                "cost": "本地免费",
                "requiresVramMb": 12_000,
                "note": _engine_note(
                    "Hunyuan3D-2.1",
                    vram_mb,
                    12_000,
                    "权重未安装，或显存不足 12 GB",
                ),
            },
            {
                "id": "tripo3d",
                "available": bool(tripo_api.health().get("key_loaded")),
                "local": False,
                "label": "Tripo",
                "quality": "高（PBR）",
                "cost": "按额度",
                "note": "云端贴图质量最好",
            },
        ],
    }


def _detect_vram_mb() -> Optional[int]:
    """Total VRAM of the first NVIDIA card, in megabytes.

    ``nvidia-smi`` is queried directly so the number is available even when
    the Python environment has no torch: the VRAM decides whether the
    high-end engines can run at all.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        first = result.stdout.strip().splitlines()[0].strip()
        return int(first) if first.isdigit() else None
    except Exception:
        return None


def _engine_note(label: str, vram_mb: Optional[int], required_mb: int, fallback: str) -> str:
    """Explain honestly why a high-end engine is (not) available here."""
    if vram_mb is None:
        return f"未检测到 NVIDIA 显卡，{label} 无法运行"
    if vram_mb < required_mb:
        return f"当前显卡显存 {vram_mb // 1024} GB，{label} 需要 {required_mb // 1024} GB 以上"
    return f"显存满足（{vram_mb // 1024} GB），但权重尚未安装"

@app.get("/api/session/{sid}/result")
def session_result(sid: str):
    """Return the final preview/3D-model artifacts for a session, if ready."""
    sd = session_dir(sid)
    if not os.path.isdir(sd):
        raise HTTPException(404, "no such session")
    log = os.path.join(sd, "_progress.log")
    latest_step = None
    # Fast path: if previews/ already has files, treat as ready even if
    # the progress-log async writer hasn't caught up yet.
    pdir = os.path.join(sd, "previews")
    has_previews = os.path.isdir(pdir) and any(
        f.startswith("img_") and f.endswith(".png") for f in os.listdir(pdir)
    )
    if has_previews:
        latest_step = "done"
    if os.path.isfile(log):
        # peek last line
        try:
            with open(log, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                tail = b""
                while size > 0 and tail.count(b"\n") < 2:
                    size -= 1
                    f.seek(size)
                    tail = f.read(4096)
                last = tail.splitlines()[-1].decode("utf-8", "ignore")
                import json as _json
                latest_step = _json.loads(last).get("step")
        except Exception:
            pass
            with open(log, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                tail = b""
                while size > 0 and tail.count(b"\n") < 2:
                    size -= 1
                    f.seek(size)
                    tail = f.read(4096)
                last = tail.splitlines()[-1].decode("utf-8", "ignore")
                import json as _json
                latest_step = _json.loads(last).get("step")
        except Exception:
            pass
    if latest_step != "done":
        raise HTTPException(202, "still processing")
    result = {"session_id": sid, "ready": True}
    pdir = os.path.join(sd, "previews")
    if os.path.isdir(pdir):
        items = []
        for fname in sorted(os.listdir(pdir)):
            if not fname.endswith(".png"):
                continue
            with open(os.path.join(pdir, fname), "rb") as f:
                blob = f.read()
            import base64 as _b64
            items.append({
                "index": int(fname.split("_")[1].split(".")[0]),
                "b64": _b64.b64encode(blob).decode(),
                "path": f"/api/data/{sid}/previews/{fname}",
            })
        result["previews"] = items
    # Optional specs/thinking if available
    specs_path = os.path.join(sd, "specs.json")
    if os.path.isfile(specs_path):
        with open(specs_path, "r", encoding="utf-8") as f:
            result["specs"] = json.load(f)
    prompt_path = os.path.join(sd, "prompt.txt")
    if os.path.isfile(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            txt = f.read()
        # Extract thinking section if present
        parts = txt.split("\n\n--- thinking ---\n", 1)
        result["prompt"] = parts[0]
        if len(parts) > 1:
            result["thinking"] = parts[1].split("\n")
    return result
@app.get("/api/progress/{sid}")
def get_progress(sid: str, since: float = 0.0):
    """Return new progress events since the given timestamp.
    Frontend polls this every 1.5s while a long task is running.
    """
    events = progress.read(sid, since_ts=since)
    latest = events[-1] if events else progress.latest(sid)
    return {"sid": sid, "events": events, "latest": latest}
@app.post("/api/previews")
def previews(req: PreviewsReq):
    """Generate previews via the prefer chain: minimax → jojo → local-sd.
    The local-sd fallback only triggers when both cloud providers fail;
    in the packaged build torch is not bundled so local-sd will raise.
    """
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    sid = req.session_id or uuid.uuid4().hex[:12]
    sd = session_dir(sid)
    pdir = os.path.join(sd, "previews")
    os.makedirs(pdir, exist_ok=True)
    pg = progress.Progress(sid, "previews")
    try:
        # Run n copies of the same prompt through the chain
        prompts = [req.prompt] * req.n
        src, results = api_image.generate_previews(
            prompts, prefer=req.prefer or "aixj",
            size="1024x1024", sid=sid,
        )
    except Exception as e:
        traceback.print_exc()
        pg.fail("这次没能生成出预览图，请再试一次")
        raise HTTPException(500, "这次没能生成出预览图，请再试一次")
    if not results:
        pg.fail("这次没能生成出预览图，请再试一次")
        raise HTTPException(500, "这次没能生成出预览图，请再试一次")
    items = []
    n_skipped = 0
    for i, (blob, tag) in enumerate(results):
        if blob is None:
            n_skipped += 1
            continue
        path = os.path.join(pdir, f"img_{i}.png")
        with open(path, "wb") as f:
            f.write(blob)
        items.append({"index": i, "seed": i, "tag": tag, "source": src,
                      "b64": base64.b64encode(blob).decode(),
                      "path": f"/api/data/{sid}/previews/img_{i}.png"})
    if not items:
        pg.fail("这次没能生成出预览图，请再试一次")
        raise HTTPException(500, "这次没能生成出预览图，请再试一次")
    pg.done(f"已生成 {len(items)} 张" + (f" ({n_skipped} 张跳过)" if n_skipped else ""))
    with open(os.path.join(sd, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(req.prompt)
    return {"session_id": sid, "previews": items, "prompt": req.prompt, "source": src}

@app.post("/api/refine")
def refine_preview_endpoint(req: RefineReq):
    """Edit an existing preview following the annotated instruction.

    Body may carry either the annotated canvas (data URL / base64) or rely on
    the stored preview image. The result is saved as previews/refined_0.png so
    the frontend can swap it into the canvas / 3D pipeline.
    """
    if not req.instruction.strip():
        raise HTTPException(400, "修改指令不能为空")
    sid = req.session_id or uuid.uuid4().hex[:12]
    sd = session_dir(sid)
    pdir = os.path.join(sd, "previews")
    os.makedirs(pdir, exist_ok=True)
    pg = progress.Progress(sid, "previews")

    reference: Optional[bytes] = None
    if req.image:
        raw = req.image
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        try:
            reference = base64.b64decode(raw)
        except Exception as e:
            raise HTTPException(400, f"批注图无法解析：{e}")
        if not reference:
            raise HTTPException(400, "批注图内容为空")
    else:
        src = os.path.join(pdir, f"img_{req.image_index}.png")
        if not os.path.isfile(src):
            raise HTTPException(404, "预览图不存在，请先生成预览")
        with open(src, "rb") as f:
            reference = f.read()

    try:
        blob, tag = api_image.refine_preview(reference, req.instruction, sid=sid)
    except RuntimeError as e:
        pg.fail("这次没能按批注修改成功，请再试一次")
        raise HTTPException(502, "这次没能按批注修改成功，请再试一次")
    except Exception as e:
        traceback.print_exc()
        pg.fail("这次没能按批注修改成功，请再试一次")
        raise HTTPException(500, "这次没能按批注修改成功，请再试一次")

    out_path = os.path.join(pdir, "refined_0.png")
    with open(out_path, "wb") as f:
        f.write(blob)
    pg.done("AI 已按批注修改完成")
    return {
        "session_id": sid,
        "source": tag,
        "instruction": req.instruction,
        "previews": [{
            "index": 0,
            "b64": base64.b64encode(blob).decode(),
            "path": f"/api/data/{sid}/previews/refined_0.png",
        }],
    }

@app.post("/api/3d")
def to_3d(req: ThreeDReq):
    pg = progress.Progress(req.session_id, "3d-triposr", reset=True)
    os.environ["PROGRESS_SID"] = req.session_id
    pg.emit("preprocess", 10, "正在处理你的设计稿…", "queued")
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if not os.path.isfile(src):
        raise HTTPException(404, "preview not found")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)
    try:
        info = triposr_runner.generate_3d(src, out)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, "这次没能生成出模型，请再试一次")
    # Re-export cleaned mesh (single connected body, flat base on z=0).
    try:
        import trimesh
        cleaned = trimesh.load(info["stl"], force="mesh")
        cleaned = mesh_postprocess.clean_for_print(cleaned, add_base=True)
        cleaned.export(info["stl"])
        cleaned.export(info["obj"])
        mesh_postprocess.export_view_glb(cleaned, info["glb"])
        info["vertices"] = len(cleaned.vertices)
        info["faces"] = len(cleaned.faces)
        info["extents_mm"] = cleaned.extents.tolist()
    except Exception as e:
        print(f"[postprocess] clean_for_print skipped: {e}", flush=True)
    return {"session_id": req.session_id, **info, "model_url": f"/api/data/{req.session_id}/model/mesh.glb"}
class ThreeDCartoonReq(BaseModel):
    session_id: str
    image_index: int = 0
    # Optional data URL produced by the 宜小智 canvas editor.  When present,
    # the edited image becomes the exact source for the printable relief.
    custom_image: Optional[str] = None
    layers: int = 6
    layer_step_mm: float = 4.0
    base_mm: float = 3.0
    target_side: int = 512
    back_scale: float = 0.95
    back_thickness_mm: float = 10.0
    keychain_hole: bool = False
    keychain_diameter_mm: float = 5.0
    thickness_mm: float = 14.0
    max_depth_mm: float = 22.0
    smooth_sigma: float = 2.4
    dome_sigma: float = 4.5
    base_disk_mm: float = 2.5
    base_disk_scale: float = 1.05
    edge_falloff_mm: float = 4.0
@app.post("/api/3d_cartoon")
def to_3d_cartoon(req: ThreeDCartoonReq):
    """Cartoon-optimized 3D path.
    Builds a multi-layer 3D relief from the alpha mask of the chosen preview.
    Always succeeds, always looks like the cartoon, always prints cleanly.
    This is the recommended default for cute cartoon characters.
    """
    pg = progress.Progress(req.session_id, "3d-cartoon", reset=True)
    pg.emit("preprocess", 10, "正在读取你的设计稿…", "queued")
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if req.custom_image:
        try:
            from io import BytesIO
            from PIL import Image as _PILImage

            if not req.custom_image.startswith("data:image/") or "," not in req.custom_image:
                raise ValueError("custom_image 必须是图片 data URL")
            _, encoded = req.custom_image.split(",", 1)
            if len(encoded) > 12_000_000:
                raise ValueError("custom_image 过大")
            blob = base64.b64decode(encoded, validate=True)
            edited_path = os.path.join(sd, "previews", "custom_edit.png")
            _PILImage.open(BytesIO(blob)).convert("RGBA").save(edited_path, "PNG")
            src = edited_path
        except Exception as exc:
            pg.fail("这次没能读取你的画布，请再试一次")
            raise HTTPException(400, f"无法读取画布编辑结果: {exc}") from exc
    if not os.path.isfile(src):
        pg.fail("这次没能找到预览图，请再试一次")
        raise HTTPException(404, "preview not found")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)
    pg.emit("layer", 40, f"正在把设计稿叠成 {req.layers} 层立体浮雕…", "geometry")
    try:
        info = mesh_postprocess.cartoon_3d_figurine(
            src, out,
            base_mm=req.base_mm,
            thickness_mm=req.thickness_mm,
            back_thickness_mm=req.back_thickness_mm,
            back_scale=req.back_scale,
            max_depth_mm=req.max_depth_mm,
            target_side=req.target_side,
            smooth_sigma=req.smooth_sigma,
            dome_sigma=req.dome_sigma,
            base_disk_mm=req.base_disk_mm,
            base_disk_scale=req.base_disk_scale,
            edge_falloff_mm=req.edge_falloff_mm,
        )
    except Exception as e:
        traceback.print_exc()
        pg.fail("这次没能生成出模型，请再试一次")
        raise HTTPException(500, f"cartoon relief error: {e}")
    pg.done("立体模型已经做好啦")
    return {
        "session_id": req.session_id,
        **info,
        "model_url": f"/api/data/{req.session_id}/model/mesh.glb",
    }
@app.post("/api/print")
def to_print(req: PrintReq):
    sd = session_dir(req.session_id)
    candidates_dir = os.path.join(sd, "models_multi")
    if req.seed is not None:
        stl = os.path.join(candidates_dir, f"seed_{req.seed}", "mesh.stl")
    else:
        stl = os.path.join(sd, "model", "mesh.stl")
    if not os.path.isfile(stl):
        # back-compat fallback
        legacy = os.path.join(sd, "model", "mesh.stl")
        if os.path.isfile(legacy):
            stl = legacy
        else:
            raise HTTPException(404, f"no mesh at {stl}")
    return bambu.open_in_bambu(stl)
# ---------------------------------------------------------------------------
# AI 思考模式路由
# ---------------------------------------------------------------------------
@app.post("/api/think")
def think(req: ThinkReq):
    """Stage 1: 把客户的口语化描述拆成 N 个差异化 sub-prompt。"""
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    specs, source, info = llm_client.elaborate(req.prompt, n=req.n)
    return {
        "thinking": info["thinking"],
        "source": source,
        "model": info["model"],
        "elapsed_ms": info["elapsed_ms"],
        "fallback_reason": info["fallback_reason"],
        "specs": [
            {"pose": s.pose, "style": s.style, "sub_prompt": s.sub_prompt, "caption": s.caption}
            for s in specs
        ],
    }
def _previews_v2_worker(req: PreviewsV2Req, sid: str):
    """Background worker that does all the heavy work for /api/previews_v2.
    Writes progress events under data/{sid}/_progress.log so the frontend can poll
    them in real time while this runs in a thread.
    """
    import llm_client, api_image
    sd = session_dir(sid)
    pdir = os.path.join(sd, "previews")
    os.makedirs(pdir, exist_ok=True)
    t_total = time.time()
    specs, source, info = llm_client.elaborate(req.prompt, n=max(2, min(req.n, 8)))
    sub_prompts = [s.sub_prompt for s in specs]
    captions = [s.caption for s in specs]
    thinking = list(info["thinking"])
    thinking.append(f"开始生成 {req.n} 张预览 (prefer={req.prefer})")
    pg = progress.Progress(sid, 'previews')
    pg.emit('thinking', 5, f'规则增强完成，准备生成 {req.n} 张预览')
    try:
        img_source, raw_items = api_image.generate_previews(
            sub_prompts, prefer=req.prefer if req.prefer else 'aixj',
            size='1024x1024', sid=sid,
        )
    except Exception as e:
        pg.fail('这次没能生成出预览图，请再试一次')
        return
    if not raw_items:
        pg.fail('这次没能生成出预览图，请再试一次')
        return
    items, n_saved, n_failed = _save_preview_items(raw_items, pdir, captions, sub_prompts, sid, req.n, pg)
    if not items:
        pg.fail('图片服务暂时不可用，请稍后再试')
        return
    if n_failed:
        thinking.append(f"图片来源: {img_source} ({n_saved}/{req.n} 张成功,{n_failed} 张失败)")
        pg.emit('preview-partial', 95, f'{n_saved}/{req.n} 张可用,{n_failed} 张失败')
    else:
        thinking.append(f"图片来源: {img_source} ({n_saved}/{req.n})")
    thinking.append(f"全部完成，耗时 {int((time.time()-t_total)*1000)/1000:.1f}s")
    with open(os.path.join(sd, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(req.prompt + "\n\n--- thinking ---\n" + "\n".join(thinking))
    with open(os.path.join(sd, "specs.json"), "w", encoding="utf-8") as f:
        json.dump([{"caption": c, "sub_prompt": p} for c, p in zip(captions, sub_prompts)],
                  f, ensure_ascii=False, indent=2)
    pg.done(f'预览 {len(items)}/{req.n} 张完成')
@app.post("/api/previews_v2")
def previews_v2(req: PreviewsV2Req):
    """Stage 2: 先 think，再批量出图。立刻返回 sid，后续进度通过 /api/progress/{sid} 拉取。"""
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    sid = req.session_id or uuid.uuid4().hex[:12]
    # Reserve the session folder so the frontend can poll even before worker
    # touches it. The Progress() inside the worker will append to this log.
    sd = session_dir(sid)
    os.makedirs(sd, exist_ok=True)
    # Write a placeholder so the poller sees *something* immediately.
    progress.Progress(sid, 'previews')
    # Fire the real work on a thread. Uvicorn workers are sync, so we use a
    # background thread; daemon=True so it dies with the process.
    threading.Thread(target=_previews_v2_worker, args=(req, sid), daemon=True).start()
    return {
        "session_id": sid,
        "thinking": [],
        "think_source": "queued",
        "previews": [],
        "queued": True,
    }
@app.post("/api/3d_multi")
def to_3d_multi(req: ThreeDMultiReq):
    """Stage 3: 用多种子跑 TripoSR，返回 K 个候选 glb/stl 让用户挑。"""
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if not os.path.isfile(src):
        raise HTTPException(404, "preview not found")
    out_dir = os.path.join(sd, "models_multi")
    os.makedirs(out_dir, exist_ok=True)
    seeds = req.seeds[:4] or [42, 137, 2024]
    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    # Pre-load source image once
    from PIL import Image as _PILImage
    try:
        import numpy as np
        _rng = np.random.default_rng(0)
    except Exception:
        _rng = None
    src_img = _PILImage.open(src).convert("RGB")
    aug_dir = os.path.join(out_dir, "_aug")
    os.makedirs(aug_dir, exist_ok=True)
    for idx, s in enumerate(seeds):
        # Per-seed deterministic augmentation so the 3D outputs differ.
        import math
        rs = int(s) & 0xFFFF
        angle = ((rs % 13) - 6) * 0.7   # -4.2 .. +4.2 deg
        scale = 1.0 + (((rs >> 3) % 9) - 4) * 0.02  # 0.92 .. 1.08
        tx = (((rs >> 5) % 7) - 3) * 0.03  # -0.09 .. +0.09
        ty = (((rs >> 8) % 7) - 3) * 0.03
        aug_path = os.path.join(aug_dir, f"seed_{s}.png")
        if not os.path.isfile(aug_path):
            img = src_img.rotate(angle, resample=_PILImage.BICUBIC, fillcolor=(255, 255, 255))
            new_w = int(img.size[0] * scale)
            new_h = int(img.size[1] * scale)
            img = img.resize((new_w, new_h), _PILImage.BICUBIC)
            canvas = _PILImage.new("RGB", src_img.size, (255, 255, 255))
            ox = (src_img.size[0] - new_w) // 2 + int(tx * new_w)
            oy = (src_img.size[1] - new_h) // 2 + int(ty * new_h)
            canvas.paste(img, (ox, oy))
            canvas.save(aug_path)
        target = os.path.join(out_dir, f"seed_{s}")
        try:
            info = triposr_runner.generate_3d(aug_path, target)
            items.append({
                "seed": int(s),
                "aug_path": aug_path,
                "glb_url": f"/api/data/{req.session_id}/models_multi/seed_{s}/mesh.glb",
                "stl_url": f"/api/data/{req.session_id}/models_multi/seed_{s}/mesh.stl",
                "extents_mm": info.get("extents_mm") or info.get("extents"),
            })
        except Exception as e:
            errors.append({"seed": int(s), "error": str(e)[:200]})










    return {
        "session_id": req.session_id,
        "candidates": items,
        "errors": errors,
    }
class ThreeDV2Req(BaseModel):
    session_id: str
    image_index: int = 0
    views: int = 1  # 1 supplement view (front + 1 alternate) - keeps TripoSR within 6GB VRAM
def _view_prompts(base_prompt: str, n: int) -> List[str]:
    """Generate n distinct view prompts to supplement the front view."""
    style_suffix = ", soft pastel cel-shaded cartoon, simple shapes, full body, kid-friendly, white background, no text, single object, clean silhouette, 3d printable figurine"
    # single best supplement view = 3/4 angle (front legibility + side contour)
    templates = [
        "shown from three-quarter angle facing camera right, both character sides visible",
        "shown from the right side, profile view facing camera right",
    ]
    out = []
    for i in range(min(n, len(templates))):
        out.append(f"{base_prompt}, {templates[i]}{style_suffix}")
    return out
@app.post("/api/3d_v2")
def to_3d_v2(req: ThreeDV2Req):
    """Multi-view reconstruction.
    1) Use the user-selected preview as the front view.
    2) Generate `views` supplementary views via jojo-image API using different angle prompts.
    3) Preprocess all views (background removal, foreground resize).
    4) Feed all views into TripoSR for fused reconstruction.
    5) Save mesh.glb / mesh.obj / mesh.stl and return single mesh.
    """
    sd = session_dir(req.session_id)
    pdir = os.path.join(sd, "previews")
    previews_meta = os.path.join(sd, "specs.json")
    src = os.path.join(pdir, f"img_{req.image_index}.png")
    pg = progress.Progress(req.session_id, "3d-v2", reset=True)
    if not os.path.isfile(src):
        pg.fail(f"预览图不存在: {src}")
        raise HTTPException(404, "preview not found")
    # Load the user's original prompt + sub-prompt for this index to keep viewpoint consistent
    try:
        with open(previews_meta, "r", encoding="utf-8") as f:
            specs = json.load(f)
        base_prompt = specs[req.image_index]["sub_prompt"] if specs and req.image_index < len(specs) else "cute cartoon character"
    except Exception:
        base_prompt = "cute cartoon character, simple shape, kid friendly"
    t_total = time.time()
    print(f"[3d_v2] generating {req.views} supplementary views for preview {req.image_index}")
    view_prompts = _view_prompts(base_prompt, req.views)
    img_source, raw_items = api_image.generate_previews(
        view_prompts, prefer="minimax", size="1024x1024"
    )
    # Skip None entries (provider had partial outage) but keep the chain
    # going if we got at least one usable view.
    valid_items = [(b, t) for b, t in (raw_items or []) if b is not None]
    if not valid_items:
        pg.fail("补充视角生图失败")
        raise HTTPException(500, "supplementary view generation failed")
    views_dir = os.path.join(sd, "models_v2_views")
    os.makedirs(views_dir, exist_ok=True)
    view_paths: List[str] = [src]
    for i, (blob, tag) in enumerate(valid_items):
        p = os.path.join(views_dir, f"view_{i}.png")
        with open(p, "wb") as f:
            f.write(blob)
        view_paths.append(p)
    print(f"[3d_v2] {len(view_paths)} total views prepared in {time.time()-t_total:.1f}s")
    pg.emit("build", 60, "正在组合多个视角，让模型更完整…", "geometry")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)
    try:
        info = triposr_runner.generate_3d(view_paths, out, mc_res=128, threshold=15.0)
    except Exception as e:
        traceback.print_exc()
        pg.fail("这次没能生成出模型，请再试一次")
        raise HTTPException(500, "这次没能生成出模型，请再试一次")
    try:
        _faces = int(info.get("faces", 0))
    except Exception:
        _faces = 0
    pg.done("3D 模型已经做好啦")
    return {
        "session_id": req.session_id,
        "image_index": req.image_index,
        "view_count": len(view_paths),
        "view_paths": [f"/api/data/{req.session_id}/models_v2_views/view_{i}.png" for i in range(req.views)],
        "supplementary_source": img_source,
        "elapsed_s": int((time.time() - t_total) * 1000) / 1000,
        **info,
        "model_url": f"/api/data/{req.session_id}/model/mesh.glb",
    }
class ThreeDTripoReq(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    image_index: int = 0
    target_height_mm: float = 70.0
    model_version: str = "v3.1-20260211"
    texture_quality: str = "detailed"
    face_limit: Optional[int] = None


class ThreeDHYReq(BaseModel):
    session_id: str
    image_index: int = 0
    steps: int = 5
    octree: int = 96
@app.post("/api/3d_hy")
def to_3d_hy(req: ThreeDHYReq):
    pg = progress.Progress(req.session_id, "3d-hunyuan", reset=True)
    pg.emit("warmup", 5, "正在准备 3D 模型…", "queued")
    os.environ["PROGRESS_SID"] = req.session_id
    """High-quality 3D using Hunyuan3D-2 mini (Tencent 3.5B image-to-3D model).
    First call loads the model (~3 min). Subsequent calls reuse GPU weights.
    Per-mesh latency: ~90s with steps=5 octree=96.
    """
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if not os.path.isfile(src):
        raise HTTPException(404, "preview not found")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)
    try:
        info = hunyuan_runner.generate_3d(
            src, out,
            num_inference_steps=req.steps,
            octree_resolution=req.octree,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, "这次没能生成出模型，请再试一次")
    # Re-export cleaned mesh: drop debris, keep largest body, sit on z=0, add base.
    try:
        import trimesh
        cleaned = trimesh.load(info["mesh_stl"], force="mesh")
        # Hunyuan's native object axis is Y-up; convert it before making a
        # slicer-ready Z-up base plate.
        cleaned = mesh_postprocess.clean_for_print(cleaned, add_base=True, source_up="y")
        cleaned.export(info["mesh_stl"])
        cleaned.export(info["mesh_obj"])
        mesh_postprocess.export_view_glb(cleaned, info["mesh_glb"])
        info["faces"] = len(cleaned.faces)
        info["extents_mm"] = cleaned.extents.tolist()
    except Exception as e:
        print(f"[postprocess] hunyuan clean skipped: {e}", flush=True)
    return {
        "session_id": req.session_id,
        "engine": "hunyuan3d-2mini",
        **info,
        "model_url": f"/api/data/{req.session_id}/model/mesh.glb",
    }
@app.post("/api/3d_tripo")
def to_3d_tripo(req: ThreeDTripoReq):
    """Tripo3D cloud image-to-3D (v3.1, PBR textured).

    Pipeline: upload preview -> POST /task -> poll -> download PBR GLB ->
    convert to STL/OBJ/GLB for printing + viewing.
    """
    if not tripo_api.API_KEY:
        raise HTTPException(503, "3D 生成服务暂时不可用，请检查服务端密钥配置")
    pg = progress.Progress(req.session_id, "3d-tripo", reset=True)
    # Only the cached balance is read here.  The probe itself runs in the
    # background: asking for the balance on the request path would stall the
    # visitor for seconds whenever the provider is slow, which is exactly
    # the "卡住" the workbench must never show.
    bal = _cached_tripo_balance()
    if isinstance(bal, dict) and bal.get("ok"):
        credits = int(bal.get("balance", 0))
        if credits < 30:
            pg.fail("生成额度暂时用完了，请稍后再试一次")
            raise HTTPException(402, "3D 生成额度暂时用完了，请稍后再试一次")
    # A cold cache means the balance is simply unknown, not zero.  The
    # background probe is already on its way; if the credits really are gone
    # Tripo answers with an error and the engine chain moves on to the next
    # provider, so there is nothing to wait for here.
    pg.emit("upload", 5, "正在上传你的设计稿…", "queued")
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if not os.path.isfile(src):
        raise HTTPException(404, "preview not found")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)

    def on_poll(t):
        try:
            pct = int(t.get("progress", 0))
        except Exception:
            pct = 0
        status = (t.get("status") or "running").upper()
        pg.emit(f"tripo-{status}", max(10, min(95, pct)), "正在生成立体结构…", "geometry")

    def on_net_fail(fail_count, last_err):
        pg.emit("tripo-net-flicker", 80, "网络有点慢，正在继续等待…", "geometry")

    t0 = time.time()
    _orig_poll = tripo_api.poll_until_done
    def _poll_with_hook(*a, **kw):
        kw.setdefault("on_persistent_failure", on_net_fail)
        return _orig_poll(*a, **kw)
    tripo_api.poll_until_done = _poll_with_hook
    try:
        result = tripo_api.image_to_model(
            src, out,
            model_version=req.model_version,
            texture=True, pbr=True,
            texture_quality=req.texture_quality,
            face_limit=req.face_limit,
            max_wait=300.0,
            on_poll=on_poll,
        )
    except Exception as e:
        traceback.print_exc()
        recovered = None
        try:
            state_file = os.path.join(out, "_tripo_state.json")
            if os.path.isfile(state_file):
                import json as _json
                with open(state_file, "r", encoding="utf-8") as _f:
                    recovered = _json.load(_f)
        except Exception:
            pass
        if recovered and recovered.get("task_id"):
            # The task id only helps the operator; it must not reach the
            # visitor, who should just see a friendly retry hint.
            print(f"[tripo3d] recoverable task_id={recovered['task_id']}", flush=True)
        pg.fail("这次没能生成出模型，请再试一次")
        raise HTTPException(
            status_code=500,
            detail={
                "error": f"tripo3d error: {e}",
                "engine": "tripo3d",
                "fallback_suggested": "3d_multi or 3d_cartoon",
                "task_id": (recovered or {}).get("task_id"),
                "image_token": (recovered or {}).get("image_token"),
                "hint": "网络/SSL 抖动,或 Tripo 服务端暂不可用",
            },
        )
    finally:
        tripo_api.poll_until_done = _orig_poll

    pbr_glb = result["files"].get("model_pbr.glb") or result["files"].get("model.glb")
    if not pbr_glb or not os.path.isfile(pbr_glb):
        pg.fail("这次没能生成出模型，请再试一次")
        raise HTTPException(500, "这次没能生成出模型，请再试一次")
    pg.emit("postprocess", 96, "正在优化模型，方便直接打印…", "optimizing")
    try:
        printable = tripo_api.process_for_print(
            pbr_glb, out,
            target_height_mm=req.target_height_mm,
            keep_visual=True,
        )
    except Exception as e:
        traceback.print_exc()
        pg.fail(f"模型整理时出了点问题，请再试一次（{e}）")
        raise HTTPException(500, f"postprocess error: {e}")

    faces = int(printable.get("faces", 0))
    vertices = int(printable.get("vertices", 0))
    ext = printable.get("extents_mm", "0,0,0").split(",")
    extents_mm = [float(x) for x in ext] + [0.0] * (3 - len(ext))
    # The model stands on the print bed, so its height is the Z extent.
    pg.done(f"3D 模型已经做好啦（高 {extents_mm[2]:.0f}mm）")
    return {
        "session_id": req.session_id,
        "engine": "tripo3d",
        "task_id": result["task_id"],
        "model_version": result["model_version"],
        "model_url": f"/api/data/{req.session_id}/model/mesh.glb",
        "stl_url": f"/api/data/{req.session_id}/model/mesh.stl",
        "obj_url": f"/api/data/{req.session_id}/model/mesh.obj",
        "faces": faces,
        "vertices": vertices,
        "extents_mm": extents_mm,
        "elapsed_s": round(time.time() - t0, 1),
        "credits_remaining": credits,
        "tripo_result": {k: v for k, v in result.items() if k not in ("raw",)},
    }


class ThreeDHYCloudReq(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    image_index: int = 0
    target_height_mm: float = 70.0
    model: str = "3.1"
    enable_pbr: bool = True
    face_count: int = 500000


@app.post("/api/3d_hycloud")
def to_3d_hycloud(req: ThreeDHYCloudReq):
    """Tencent Cloud Hunyuan3D 专业版 (fallback between Tripo3D and local).

    Pipeline: submit image job -> poll until DONE -> download COS zip ->
    pick .glb -> clean/scale for print.
    """
    import hunyuan_cloud_api as hyc
    keys = hyc.health()
    if not keys["key_loaded"]:
        raise HTTPException(503, "3D 生成服务暂时不可用，请检查服务端密钥配置")
    pg = progress.Progress(req.session_id, "3d-hunyuan-cloud", reset=True)
    sd = session_dir(req.session_id)
    src = os.path.join(sd, "previews", f"img_{req.image_index}.png")
    if not os.path.isfile(src):
        raise HTTPException(404, "preview not found")
    out = os.path.join(sd, "model")
    os.makedirs(out, exist_ok=True)

    t0 = time.time()

    def on_poll(resp):
        try:
            status = str(resp.get("Status", "")).upper()
            # Ramp the bar while the cloud job renders so the visitor sees the
            # model actually progressing instead of a frozen 0%.
            elapsed = time.time() - t0
            pct = 15 + min(70, int(elapsed * 70.0 / 300.0))
            pg.emit(f"hunyuan3d-{status.lower()}", pct, "正在生成立体结构…", "geometry")
        except Exception:
            pass

    try:
        result = hyc.image_to_model(
            src, out,
            model=req.model,
            enable_pbr=req.enable_pbr,
            face_count=req.face_count,
            max_wait=420.0,
            target_height_mm=req.target_height_mm,
            on_poll=on_poll,
        )
    except Exception as e:
        traceback.print_exc()
        pg.fail(f"这次没能生成出模型，请再试一次（{e}）")
        raise HTTPException(500, {"error": "这次没能生成出模型，请再试一次"})
    faces = int(result.get("faces", 0))
    ext = result.get("extents_mm", "0,0,0")
    if isinstance(ext, list):
        ext_str = ",".join(str(x) for x in ext[:3])
    else:
        ext_str = str(ext)
    pg.emit("texturing", 92, "正在整理颜色与材质…", "texturing")
    pg.done("3D 模型已经做好啦")
    return {
        "session_id": req.session_id,
        "engine": "hunyuan3d-cloud",
        "job_id": result.get("job_id"),
        "credits_consumed": result.get("credits_consumed"),
        "model_url": f"/api/data/{req.session_id}/model/mesh.glb",
        "stl_url": f"/api/data/{req.session_id}/model/mesh.stl",
        "obj_url": f"/api/data/{req.session_id}/model/mesh.obj",
        "faces": faces,
        "vertices": result.get("vertices", 0),
        "extents_mm": ext_str,
        "elapsed_s": round(time.time() - t0, 1),
    }


@app.get("/api/bambu")
def bambu_status():
    p = bambu.find_bambu_path()
    return {"found": bool(p), "path": p}


class BambuSetReq(BaseModel):
    path: str


class SoftwareOpenReq(BaseModel):
    software_id: str
    session_id: str
    fmt: str = "stl"
    image_index: int = 0


class FromImageReq(BaseModel):
    image: str
    svg: Optional[str] = None
    prompt: str = ""
    source: str = "canvas"


def _decode_data_url_image(data_url: str) -> bytes:
    if not data_url.startswith("data:image/") or "," not in data_url:
        raise HTTPException(400, "图片必须是 image data URL")
    _, encoded = data_url.split(",", 1)
    if len(encoded) > 24_000_000:
        raise HTTPException(413, "图片过大")
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(400, f"图片数据无效：{exc}") from exc


@app.post("/api/session/from-image", status_code=201)
def session_from_image(req: FromImageReq):
    """Store a composed canvas image as a fresh modelling session.

    The canvas composite becomes the real image-to-3D input: it is written as
    `previews/img_0.png` so every existing engine can consume it unchanged.
    """
    blob = _decode_data_url_image(req.image)
    try:
        from io import BytesIO
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(blob)) as decoded:
            decoded.load()
            if max(decoded.size) > 4096:
                raise HTTPException(413, "图片尺寸过大")
            if decoded.mode not in ("RGBA", "RGB"):
                decoded = decoded.convert("RGBA")
            sid = uuid.uuid4().hex[:12]
            previews = os.path.join(session_dir(sid), "previews")
            os.makedirs(previews, exist_ok=True)
            decoded.save(os.path.join(previews, "img_0.png"), "PNG")
            width, height = decoded.size
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"图片无法读取：{exc}") from exc

    if req.svg:
        svg = req.svg.strip()
        if len(svg) > 24_000_000:
            raise HTTPException(413, "SVG 过大")
        if "<svg" not in svg.lower():
            raise HTTPException(400, "SVG 内容无效")
        lowered = svg.lower()
        if "<script" in lowered or "onload=" in lowered or "onclick=" in lowered:
            raise HTTPException(400, "SVG 含有不允许的脚本内容")
        with open(os.path.join(previews, "img_0.svg"), "w", encoding="utf-8") as handle:
            handle.write(svg)

    if req.prompt:
        with open(os.path.join(DATA, sid, "prompt.txt"), "w", encoding="utf-8") as handle:
            handle.write(req.prompt)
    with open(os.path.join(DATA, sid, "_source.json"), "w", encoding="utf-8") as handle:
        json.dump({"source": req.source, "created_at": int(time.time())}, handle, ensure_ascii=False)
    return {
        "session_id": sid,
        "preview_url": f"/api/data/{sid}/previews/img_0.png",
        "svg_url": f"/api/data/{sid}/previews/img_0.svg" if req.svg else None,
        "width": width,
        "height": height,
    }


@app.post("/api/bambu")
def bambu_set(req: BambuSetReq):
    p = (req.path or "").strip()
    if not p or not os.path.isfile(p):
        raise HTTPException(404, f"file not found: {p}")
    os.environ["BAMBU_STUDIO_EXE"] = p
    return {"ok": True, "path": p, "saved_to": "env:BAMBU_STUDIO_EXE"}


@app.get("/api/software/detect")
def software_detect():
    """Detect local design, slicer and laser tools without launching anything."""
    return {"tools": software_integrations.detect_software()}


def _resolve_laser_artwork(artwork_session_id: Optional[str], artwork_image_index: int) -> str:
    """Locate the visitor's own artwork (their model preview) for the card front.

    The laser card is the last step of the 创作 -> 3D -> 切割 chain, so its
    front carries the very preview the visitor designed.  An edited image
    wins over the generated one, because the 创作面板 writes it there.
    """
    sid = (artwork_session_id or "").strip()
    if not sid or not SESSION_ID_RE.fullmatch(sid):
        return ""

    try:
        index = max(0, min(9, int(artwork_image_index or 0)))
    except (TypeError, ValueError):
        index = 0

    previews = os.path.join(session_dir(sid), "previews")
    edited = os.path.join(previews, "custom_edit.png")
    if os.path.isfile(edited):
        return edited

    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = os.path.join(previews, f"img_{index}{ext}")
        if os.path.isfile(candidate):
            return candidate
    return ""


class LaserCardReq(BaseModel):
    """User-editable fields for the front side; the back is a fixed template."""
    name: str = ""
    title: str = ""
    unit: str = ""
    contact: str = ""
    slogan: str = ""
    theme: str = "#0B5FA8"
    accent: str = "#F5A623"
    bg_style: str = "gradient"
    note: str = ""
    back_template: str = "activity_yichang"
    front_template: str = ""
    back_caption: str = "宜昌市第四届中小学生数理文化活动"
    back_title: str = ""
    back_subtitle: str = ""
    session_id: Optional[str] = None
    artwork_session_id: Optional[str] = None
    artwork_image_index: int = 0


@app.get("/api/laser/templates")
def laser_templates():
    """List available fixed back-side templates."""
    root = laser_card.ensure_templates(DATA)
    return {"templates": laser_card.list_templates(root)}


@app.get("/api/laser/template-preview/{slug}")
def laser_template_preview(slug: str):
    """The back face of one template, rendered with the activity theme.

    The studio shows this in the picker so the visitor sees the real card
    back -- theme title included -- instead of a bare background.
    """
    root = laser_card.ensure_templates(DATA)
    payload = laser_card.render_template_preview(
        root,
        slug,
        title=laser_card.DEFAULT_BACK_TITLE,
        subtitle=laser_card.DEFAULT_BACK_SUBTITLE,
    )
    if not payload:
        raise HTTPException(404, f"找不到卡片背景模板：{slug}")
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


class LaserBackgroundReq(BaseModel):
    """One-sentence description -> an AI generated card face.

    ``side`` picks which face the artwork belongs on: "back" is the activity
    background, "front" is the printed face that carries the visitor's name.
    """
    description: str
    name: Optional[str] = None
    side: str = "back"


def _safe_template_slug(text: Optional[str]) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", (text or "").strip())
    return cleaned[:32]


@app.post("/api/laser/background")
def laser_background(req: LaserBackgroundReq):
    """Generate a card back background from a one-line description.

    The visitor describes the look they want ("深蓝科技感、星辰与电路板…")
    and the image service produces the artwork.  The result is stored as a
    normal back template, so the cutting pipeline itself stays untouched and
    the card can still be opened in xTool straight away.
    """
    description = (req.description or "").strip()
    if not description:
        raise HTTPException(422, "请先描述你想要的背景，例如：深蓝科技感，星辰与电路板")

    side = "front" if (req.side or "back").strip().lower() == "front" else "back"
    root = laser_card.ensure_templates(DATA)
    if side == "front":
        prompt = (
            "激光切割卡片的正面主视觉，横向 16:9 横幅构图，主体集中在画面中部的横向带状区域。"
            f"风格要求：{description}。"
            "画面要求：现代科技感与卡通插画风结合，明亮通透、色彩干净、层次分明，"
            "画面上下边缘留白，主体不要贴边；"
            "不要出现任何文字、字母、数字、水印或人物脸部特写，适合印刷。"
        )
    else:
        prompt = (
            "活动主视觉背景，横向 16:9 横幅构图，用作激光切割卡片的背面。"
            f"风格要求：{description}。"
            "画面要求：现代科技感与卡通插画风结合，明亮通透、色彩干净、层次分明，"
            "画面上半部分的中部保持干净以便叠加活动主题大字；"
            "不要出现任何文字、字母、数字、水印或人物脸部特写，适合印刷。"
        )
    try:
        source, items = api_image.generate_previews([prompt], prefer="aixj", size="1024x1024")
        blob = next((b for b, _ in items if b), None)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"背景生成失败：{exc}") from exc
    if not blob:
        raise HTTPException(502, "背景生成服务暂时不可用，请稍后再试")

    try:
        import io as _io
        from PIL import Image as _PILImage

        with _PILImage.open(_io.BytesIO(blob)) as handle:
            image = handle.convert("RGB")
            # The image service answers with a square; a card back is 16:9.
            ratio = 16 / 9
            width, height = image.size
            if width / height > ratio:
                new_width = int(height * ratio)
                left = (width - new_width) // 2
                image = image.crop((left, 0, left + new_width, height))
            else:
                new_height = int(width / ratio)
                top = (height - new_height) // 2
                image = image.crop((0, top, width, top + new_height))
            image = image.resize((1600, 900), _PILImage.LANCZOS)
    except Exception as exc:
        raise HTTPException(500, f"背景处理失败：{exc}") from exc

    slug = _safe_template_slug(req.name) or f"custom_{uuid.uuid4().hex[:8]}"
    if side == "front" and not slug.startswith("front_"):
        slug = f"front_{slug}"
    target = os.path.join(root, f"{slug}.png")
    image.save(target, "PNG", optimize=True)
    label = (req.name or description).strip()[:20] or ("我的正面" if side == "front" else "我的背景")
    laser_card.register_template(root, slug, label, 100.0, 56.25, side=side)
    return {
        "id": slug,
        "name": label,
        "url": f"/api/data/laser/template/{slug}.png",
        "size_mm": {"width": 100.0, "height": 56.25},
        "side": side,
        "source": source,
        "message": "正面已生成，可以直接用在卡片正面" if side == "front" else "背景已生成，可以直接用在卡片背面",
    }


class LaserDesignReq(BaseModel):
    """One-sentence description -> AI fills the card form fields."""
    description: str
    theme: str = "#0B5FA8"
    accent: str = "#F5A623"


@app.post("/api/laser/design")
def laser_design(req: LaserDesignReq):
    """Turn a one-line description into a pre-filled laser card form.

    Uses the same LLM adapter as the thinking pipeline (MiniMax -> DeepSeek,
    rule-based fallback), so it never blocks even when the LLM is down.
    """
    import json as _json
    description = (req.description or "").strip()
    if not description:
        raise HTTPException(422, "请先描述你想要的名片，例如：张老师的科技课名片，蓝色主题")

    prompt = (
        "你是一名名片排版设计师。根据用户的描述，为一张激光切割名片（正面自由编辑、"
        "背面固定活动背景）提取以下 JSON 字段（全部用中文或原文，字符串）："
        '{"name": 姓名, "title": 职位/身份, "unit": 单位/学校, "contact": 联系方式'
        '（如电话/微信，用换行分隔多条）, "slogan": 一句标语（8~14字，简洁有力）}。\n'
        f"用户描述：{description}\n"
        "只输出 JSON，不要多余文字。"
    )
    fallback = _laser_design_fallback(description, req.theme, req.accent)
    try:
        llm_result = llm_client.llm_call(prompt, timeout=25)
    except Exception:
        return fallback
    if not llm_result or not llm_result[0]:
        return fallback
    raw = llm_result[0]
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return fallback
    try:
        parsed = _json.loads(cleaned[start:end + 1])
    except Exception:
        return fallback
    if not isinstance(parsed, dict):
        return fallback

    def _pick(keys, default=""):
        for key in keys:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return default

    name = _pick(["name", "姓名"], fallback.get("name", ""))
    return {
        "name": name[:12],
        "title": _pick(["title", "职位"], fallback.get("title", ""))[:20],
        "unit": _pick(["unit", "单位", "school"], fallback.get("unit", ""))[:30],
        "contact": _pick(["contact", "联系方式", "phone"], fallback.get("contact", ""))[:120],
        "slogan": _pick(["slogan", "标语"], fallback.get("slogan", "数理创未来 智慧启新程"))[:30],
        "theme": req.theme,
        "accent": req.accent,
        "note": "",
    }


def _laser_design_fallback(description: str, theme: str, accent: str) -> dict:
    """Rule-based extraction when the LLM is unavailable."""
    name = ""
    if "老师" in description or "师" in description:
        match = re.search(r"([\u4e00-\u9fa5]{1,3})老师", description)
        if match:
            name = match.group(1) + "老师"
    if not name:
        match = re.search(r"([\u4e00-\u9fa5]{2,4})老师|姓名[是为：:]([\u4e00-\u9fa5]{2,4})", description)
        if match:
            name = match.group(1) or match.group(2) or ""
    title = "老师" if "老师" in description else ""
    unit = "宜昌市数理文化活动组委会"
    if "学校" in description or "教育" in description:
        unit = "宜昌市中小学"
    contact = ""
    match = re.search(r"(1[3-9]\d{9})", description)
    if match:
        contact = match.group(1)
    slogan = "数理创未来 智慧启新程"
    if "科技" in description or "AI" in description.lower() or "智能" in description:
        slogan = "数理创未来 智慧启新程"
    return {
        "name": name, "title": title, "unit": unit,
        "contact": contact, "slogan": slogan,
        "theme": theme, "accent": accent, "note": "",
    }


@app.post("/api/laser_card", status_code=201)
def laser_card_generate(req: LaserCardReq):
    """Render a pre-made laser-cut business card (front editable / back fixed)
    and produce the cut SVG + PNG previews. Fully offline and deterministic."""
    try:
        spec = req.model_dump()
        artwork_path = _resolve_laser_artwork(req.artwork_session_id, req.artwork_image_index)
        if artwork_path:
            spec["artwork_path"] = artwork_path
        result = laser_card.generate(spec, DATA)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"名片生成失败：{exc}") from exc

    sid = result["session_id"]
    return {
        "session_id": sid,
        "svg_url": f"/api/data/laser/{sid}/card.svg",
        "png_url": f"/api/data/laser/{sid}/card.png",
        "front_url": f"/api/data/laser/{sid}/card_front.png",
        "back_url": f"/api/data/laser/{sid}/card_back.png",
        "size_mm": result["size_mm"],
        "back_template": result["back_template"],
        "front_template": result.get("front_template") or "",
        "has_artwork": bool(result.get("has_artwork")),
        "has_front_art": bool(result.get("has_front_art")),
        "message": "名片已生成，可打开 SVG/PNG 交给激光软件切割",
    }



class SoftwarePathReq(BaseModel):
    software_id: str
    path: str


@app.post("/api/software/path")
def software_path_set(req: SoftwarePathReq):
    """Store a user-corrected executable path for one of the known tools."""
    tool_id = (req.software_id or "").strip()
    known = {item["id"] for item in software_integrations.detect_software()}
    if tool_id not in known:
        raise HTTPException(404, f"未知的软件标识：{tool_id}")
    raw = (req.path or "").strip().strip('"')
    if not raw:
        raise HTTPException(400, "请填写软件可执行文件的完整路径")
    expanded = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
    if not os.path.isfile(expanded):
        raise HTTPException(400, f"文件不存在：{expanded}")
    if not expanded.lower().endswith(".exe"):
        raise HTTPException(400, "请填写 .exe 可执行文件的路径")
    software_integrations.save_override(tool_id, expanded)
    tool = next(
        (item for item in software_integrations.detect_software() if item["id"] == tool_id),
        None,
    )
    return {"ok": True, "tool": tool, "tools": software_integrations.detect_software()}


@app.delete("/api/software/path/{software_id}")
def software_path_reset(software_id: str):
    """Drop a corrected path and fall back to automatic detection."""
    software_integrations.clear_override(software_id)
    tools = software_integrations.detect_software()
    tool = next((item for item in tools if item["id"] == software_id), None)
    return {"ok": True, "tool": tool, "tools": tools}


@app.post("/api/software/open")
def software_open(req: SoftwareOpenReq):
    """Open an existing 宜小智 export in an installed tool.

    This endpoint deliberately does not invoke a print/cut command.  It only
    hands the file to the selected desktop application for the user to inspect
    and confirm there.
    """
    fmt = (req.fmt or "stl").lower().lstrip(".")
    if fmt not in {"stl", "obj", "glb", "png", "svg"}:
        raise HTTPException(400, "当前只支持 STL、OBJ、GLB、PNG 或 SVG 导入")
    sid = (req.session_id or "").strip()
    if not sid or any(part in sid for part in ("..", "\\", "/")):
        raise HTTPException(400, "无效的模型会话")
    if fmt in {"png", "svg"}:
        # Laser card sessions store their cut files under data/laser/<sid>/.
        laser_file = os.path.join(DATA, "laser", sid, "card.svg" if fmt == "svg" else "card.png")
        if os.path.isfile(laser_file):
            candidate = os.path.abspath(laser_file)
        else:
            safe_index = max(0, min(9, int(req.image_index)))
            preview_root = session_dir(sid)
            if fmt == "svg":
                original = os.path.join(preview_root, "previews", f"img_{safe_index}.svg")
                candidate = os.path.abspath(original)
            else:
                edited = os.path.join(preview_root, "previews", "custom_edit.png")
                original = os.path.join(preview_root, "previews", f"img_{safe_index}.png")
                candidate = os.path.abspath(edited if os.path.isfile(edited) else original)
    else:
        candidate = os.path.abspath(os.path.join(session_dir(sid), "model", f"mesh.{fmt}"))
    data_root = os.path.abspath(DATA)
    if os.path.commonpath([candidate, data_root]) != data_root:
        raise HTTPException(400, "模型路径不在宜小智数据目录内")
    try:
        tool = next((item for item in software_integrations.detect_software() if item["id"] == req.software_id), None)
        if not tool or not tool.get("available") or not tool.get("path"):
            if tool and tool.get("overrideMissing"):
                raise FileNotFoundError(
                    f"{tool['name']} 的自定义路径已失效，请在交付面板里修正路径或恢复自动检测"
                )
            raise FileNotFoundError("所选软件未检测到，请在交付面板里确认安装路径")
        result = software_integrations.open_export(tool["path"], candidate, tool["id"])
        return {"message": result.get("message", f"已在 {tool['name']} 中打开"), "tool": tool, **result}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/export/{sid}/{fmt}")
def export_model(sid: str, fmt: str, download: bool = False):
    """Serve the latest mesh in the requested format (stl|obj|glb)."""
    fmt = fmt.lower()
    if fmt not in ("stl", "obj", "glb"):
        raise HTTPException(400, "fmt must be stl|obj|glb")
    sd = session_dir(sid)
    candidate = os.path.join(sd, "model", f"mesh.{fmt}")
    if not os.path.isfile(candidate):
        raise HTTPException(404, f"mesh.{fmt} not generated yet")
    # Inline is important for GLB preview links; callers that need a download
    # can opt into an attachment with ?download=1.
    disposition = "attachment" if download else "inline"
    return FileResponse(
        candidate,
        filename=f"宜小智模型-{sid}.{fmt}",
        media_type=EXT_MIME.get("." + fmt, "application/octet-stream"),
        content_disposition_type=disposition,
    )


@app.get("/api/sessions/{sid}/parts")
def session_parts(sid: str):
    """Split a finished model into its separate bodies and export each one.

    An AI generated model often arrives as several disconnected bodies (a
    figure and its base, an arm that was not merged with the torso, ...).
    The web workbench can animate them apart, but to *print* them separately
    every body needs its own file. This endpoint writes one GLB and one STL
    per body and reports what each of them is.
    """
    import trimesh

    sd = session_dir(sid)
    # The printable body is what the visitor can actually print, so the
    # parts are split from it.  The viewer GLB keeps the paint and the
    # original shells, and would report a few hundred loose pieces.
    mesh_path = os.path.join(sd, "model", "mesh.stl")
    if not os.path.isfile(mesh_path):
        mesh_path = os.path.join(sd, "model", "mesh.glb")
    if not os.path.isfile(mesh_path):
        raise HTTPException(404, "模型还没有生成，暂时无法拆分零件")

    out_dir = os.path.join(sd, "parts")
    manifest_path = os.path.join(out_dir, "parts.json")
    # The split only has to run again when the model itself changed.
    try:
        mesh_mtime = os.path.getmtime(mesh_path)
        manifest_mtime = os.path.getmtime(manifest_path)
    except OSError:
        mesh_mtime = manifest_mtime = 0.0

    if manifest_mtime >= mesh_mtime and os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("sessionId") == sid:
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    try:
        mesh = trimesh.load(mesh_path, force="mesh")
    except Exception as exc:
        raise HTTPException(500, f"模型读取失败：{exc}") from exc

    groups = mesh_postprocess._face_groups(mesh)
    if not groups:
        raise HTTPException(500, "模型没有可拆分的几何体")

    os.makedirs(out_dir, exist_ok=True)
    parts = []
    # A body that is smaller than half a millimetre is a rendering speck,
    # not a part a user could print. The cloud generators leave a few of
    # those behind, and listing them would only add noise to the panel.
    min_extent_mm = 0.5
    # The biggest body first: it is the part a user prints as the main
    # figure, the rest are accessories.
    ordered = sorted(groups, key=len, reverse=True)
    for group in ordered:
        try:
            part = mesh_postprocess._select_faces(mesh, group)
        except Exception as exc:
            print(f"[parts] body skipped: {exc}", flush=True)
            continue
        if part is None or len(part.faces) == 0:
            continue
        if max([float(value) for value in part.extents.tolist()] or [0.0]) < min_extent_mm:
            continue
        index = len(parts) + 1
        part_name = f"part_{index}"
        glb_path = os.path.join(out_dir, f"{part_name}.glb")
        stl_path = os.path.join(out_dir, f"{part_name}.stl")
        try:
            part.export(glb_path)
            part.export(stl_path)
        except Exception as exc:
            print(f"[parts] body {index} export failed: {exc}", flush=True)
            continue
        extents = [round(float(value), 2) for value in part.extents.tolist()]
        try:
            volume = round(float(abs(part.volume)), 2)
        except Exception:
            volume = 0.0
        parts.append({
            "index": index,
            "name": "主体" if index == 1 else f"零件 {index}",
            "glb_url": f"/api/data/{sid}/parts/{part_name}.glb",
            "stl_url": f"/api/data/{sid}/parts/{part_name}.stl",
            "faces": int(len(part.faces)),
            "extents_mm": extents,
            "volume_mm3": volume,
        })

    payload = {
        "sessionId": sid,
        "count": len(parts),
        "source": "connected-components",
        "parts": parts,
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return payload


@app.get("/api/printability/{sid}")
def printability(sid: str):
    """Run a lightweight local preflight before sending a model to print."""
    stl_path = os.path.join(session_dir(sid), "model", "mesh.stl")
    if not os.path.isfile(stl_path):
        raise HTTPException(404, "printable STL is not ready")
    try:
        import trimesh
        mesh = trimesh.load(stl_path, force="mesh")
        extents = [round(float(value), 2) for value in mesh.extents.tolist()]
        checks = {
            "watertight": bool(mesh.is_watertight),
            "volume": bool(mesh.is_volume and float(mesh.volume) > 0),
            "has_faces": bool(len(mesh.faces) > 0),
            "size_ok": bool(max(extents or [0]) <= 300 and min([v for v in extents if v > 0] or [0]) >= 1),
        }
        warnings = []
        if not checks["watertight"]: warnings.append("网格存在开口，建议重新生成或修复")
        if not checks["volume"]: warnings.append("模型体积无效，暂不建议打印")
        if not checks["size_ok"]: warnings.append("模型尺寸超出常用桌面打印范围")
        return {
            "sid": sid,
            "ready": all(checks.values()),
            "checks": checks,
            "warnings": warnings,
            "faces": int(len(mesh.faces)),
            "extents_mm": extents,
        }
    except Exception as exc:
        raise HTTPException(500, f"printability check failed: {exc}")


@app.get("/api/scenes/config")
def scene_config():
    return {
        "trainerConfigured": scene_jobs.trainer_configured(),
        "provider": scene_jobs.trainer_provider(),
        "localTrainer": scene_jobs.local_trainer_configured(),
        "captureRules": {"minimumImages": 12, "recommendedImages": 32, "maximumFiles": 80},
        "acceptedCaptures": sorted(scene_jobs.IMAGE_EXTENSIONS | scene_jobs.VIDEO_EXTENSIONS),
        "acceptedResults": sorted(scene_jobs.SPLAT_EXTENSIONS),
    }


@app.post("/api/scenes", status_code=201)
async def create_scene(title: str = Form("我的真实场景"), captures: List[UploadFile] = File(...)):
    if not captures:
        raise HTTPException(422, "请选择环绕照片或视频")
    if len(captures) > 80:
        raise HTTPException(422, "单个场景最多上传 80 个文件")
    validated = []
    for upload in captures:
        name = scene_jobs.safe_name(upload.filename or "capture")
        kind = scene_jobs.capture_kind(name)
        if not kind:
            raise HTTPException(415, f"不支持的采集文件：{name}")
        validated.append((upload, name, kind))

    record = SCENE_STORE.create(title, [])
    scene_id = record["sceneId"]
    saved = []
    for index, (upload, name, kind) in enumerate(validated, start=1):
        rel_path = f"scene/captures/{index:03d}_{name}"
        abs_path = os.path.join(DATA, scene_id, *rel_path.split("/"))
        size = await _save_uploaded_file(upload, abs_path, scene_jobs.MAX_CAPTURE_BYTES)
        saved.append({
            "name": name,
            "kind": kind,
            "size": size,
            "contentType": upload.content_type or "application/octet-stream",
            "path": rel_path,
        })

    quality = scene_jobs.assess_capture(saved)
    record["captures"] = saved
    record["quality"] = quality
    record["status"] = "CAPTURE_READY" if quality["level"] != "NEEDS_MORE" else "NEEDS_MORE_CAPTURE"
    record["message"] = quality["message"]
    SCENE_STORE.save(record)
    return SCENE_STORE.public(record)


@app.get("/api/scenes/{scene_id}")
def get_scene(scene_id: str):
    record = SCENE_STORE.load(scene_id)
    if not record:
        raise HTTPException(404, "场景任务不存在")
    return SCENE_STORE.public(record)


@app.get("/api/scenes/{scene_id}/manifest")
def get_scene_manifest(scene_id: str):
    record = SCENE_STORE.load(scene_id)
    if not record:
        raise HTTPException(404, "场景任务不存在")
    public = SCENE_STORE.public(record)
    return {
        "sceneId": public["sceneId"],
        "title": public["title"],
        "quality": public["quality"],
        "captures": public["captures"],
    }


@app.post("/api/scenes/{scene_id}/submit", status_code=202)
def submit_scene(scene_id: str):
    record = SCENE_STORE.load(scene_id)
    if not record:
        raise HTTPException(404, "场景任务不存在")
    if record.get("status") == "NEEDS_MORE_CAPTURE":
        raise HTTPException(422, record.get("message") or "采集素材不足")
    try:
        if scene_jobs.local_trainer_configured():
            result = scene_jobs.start_local_training(record, os.path.join(DATA, scene_id), SCENE_STORE)
        else:
            result = scene_jobs.submit_to_trainer(record, os.path.join(DATA, scene_id))
    except RuntimeError as exc:
        record["status"] = "WAITING_FOR_TRAINER"
        record["message"] = str(exc)
        SCENE_STORE.save(record)
        raise HTTPException(503, str(exc))
    # A local worker can finish before this request handler returns.  Preserve
    # that terminal state instead of writing CLOUD_QUEUED over a READY/FAILED
    # result, then return the freshest persisted record to the client.
    if record.get("status") not in {"READY", "FAILED"}:
        record["status"] = "CLOUD_QUEUED"
        record["cloud"] = {
            "provider": scene_jobs.trainer_provider(),
            "remoteJobId": result["remoteJobId"],
            "statusUrl": result.get("statusUrl"),
        }
        record["message"] = str(result.get("message") or "云端训练任务已提交")[:240]
        SCENE_STORE.save(record)
    return SCENE_STORE.public(SCENE_STORE.load(scene_id) or record)


@app.post("/api/scenes/import", status_code=201)
async def import_scene_asset(asset: UploadFile = File(...), title: str = Form("导入的真实场景")):
    """Load an existing Gaussian Splat result without running a training job.

    GraphDECO / gsplat produce a ``.ply`` or ``.splat`` file. Training one on
    this machine needs a GPU worker, but *loading* a result that was trained
    elsewhere (or exported by another tool) has to work everywhere, so the
    file goes straight into the SuperSplat viewer.
    """
    original = scene_jobs.safe_name(asset.filename or "scene.ply", "scene.ply")
    lower = original.lower()
    if not any(lower.endswith(ext) for ext in scene_jobs.SPLAT_EXTENSIONS):
        raise HTTPException(415, "仅支持 .ply / .splat / .sog / .spz 场景成果")

    record = SCENE_STORE.create(title, [])
    scene_id = record["sceneId"]
    rel_path = f"scene/result/{original}"
    abs_path = os.path.join(DATA, scene_id, *rel_path.split("/"))
    size = await _save_uploaded_file(asset, abs_path, scene_jobs.MAX_ASSET_BYTES)
    asset_url = f"/api/data/{scene_id}/{rel_path}"
    viewer_url = (
        f"/vendor/supersplat/index.html?content={quote(asset_url, safe='/:')}"
        "&settings=/vendor/supersplat/settings.json&lang=zh-CN"
    )
    record["status"] = "READY"
    record["message"] = "真实场景已经可以探索"
    record["result"] = {
        "name": original,
        "format": os.path.splitext(lower)[1].lstrip("."),
        "size": size,
        "assetUrl": asset_url,
        "viewerUrl": viewer_url,
    }
    SCENE_STORE.save(record)
    return SCENE_STORE.public(record)


@app.post("/api/scenes/{scene_id}/asset")
async def attach_scene_asset(scene_id: str, asset: UploadFile = File(...)):
    record = SCENE_STORE.load(scene_id)
    if not record:
        raise HTTPException(404, "场景任务不存在")
    original = scene_jobs.safe_name(asset.filename or "scene.ply", "scene.ply")
    lower = original.lower()
    if not any(lower.endswith(ext) for ext in scene_jobs.SPLAT_EXTENSIONS):
        raise HTTPException(415, "仅支持 .ply / .splat / .sog / .spz 场景成果")
    rel_path = f"scene/result/{original}"
    abs_path = os.path.join(DATA, scene_id, *rel_path.split("/"))
    size = await _save_uploaded_file(asset, abs_path, scene_jobs.MAX_ASSET_BYTES)
    asset_url = f"/api/data/{scene_id}/{rel_path}"
    viewer_url = (
        f"/vendor/supersplat/index.html?content={quote(asset_url, safe='/:')}"
        "&settings=/vendor/supersplat/settings.json&lang=zh-CN"
    )
    record["status"] = "READY"
    record["message"] = "真实场景已经可以探索"
    record["result"] = {
        "name": original,
        "format": os.path.splitext(lower)[1].lstrip("."),
        "size": size,
        "assetUrl": asset_url,
        "viewerUrl": viewer_url,
    }
    SCENE_STORE.save(record)
    return SCENE_STORE.public(record)


@app.api_route("/api/data/{sid}/{rest:path}", methods=["GET", "HEAD"])
def serve_data(sid: str, rest: str):
    p = os.path.join(DATA, sid, rest)
    if not os.path.isfile(p):
        raise HTTPException(404)
    ext = os.path.splitext(p)[1].lower()
    mt = EXT_MIME.get(ext, "application/octet-stream")
    return FileResponse(p, media_type=mt)


@app.get("/api/sessions/{sid}/model")
def get_session_model(sid: str):
    """Report whether a session already has a finished 3D model.

    The studio page used to forget everything after a reload, so an already
    built model looked like it had never been generated.
    """
    sd = session_dir(sid)
    model_dir = os.path.join(sd, "model")

    def _has(name: str) -> bool:
        candidate = os.path.join(model_dir, name)
        return os.path.isfile(candidate) and os.path.getsize(candidate) > 0

    if not _has("mesh.glb"):
        return {"session_id": sid, "exists": False}
    return {
        "session_id": sid,
        "exists": True,
        "glb_url": f"/api/export/{sid}/glb",
        "stl_url": f"/api/export/{sid}/stl" if _has("mesh.stl") else None,
        "obj_url": f"/api/export/{sid}/obj" if _has("mesh.obj") else None,
        # The print prep scales the Z axis to the requested height, so a
        # finished model stands upright with Z as its height.
        "up_axis": "z",
    }


@app.get("/api/sessions/{sid}/previews")
def get_session_previews(sid: str):
    """List the preview pictures a session produced.

    The workbench opens straight from a chat, where only the session id is
    known. The full result endpoint embeds every picture as base64, which is
    far too heavy to fetch just to learn which pictures exist, so this one
    only reports their paths.
    """
    sd = session_dir(sid)
    preview_dir = os.path.join(sd, "previews")
    items = []
    if os.path.isdir(preview_dir):
        for fname in sorted(os.listdir(preview_dir)):
            if not fname.startswith("img_") or not fname.endswith(".png"):
                continue
            try:
                index = int(fname[4:-4])
            except ValueError:
                continue
            items.append({"index": index, "path": f"/api/data/{sid}/previews/{fname}"})
    items.sort(key=lambda item: item["index"])
    return {"session_id": sid, "previews": items}


# ---------------------------------------------------------------------------
# YXZ preset printable models (created once with Tripo / Hunyuan3D)
# ---------------------------------------------------------------------------
_PRESET_ROOT = None
for _candidate in (
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets", "models"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "presets", "models"),
):
    if os.path.isdir(_candidate):
        _PRESET_ROOT = _candidate
        break
if _PRESET_ROOT is None:
    _PRESET_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets", "models")
_PRESET_NAMES = {
    "pose_wave": ("招手打招呼", "白色宇航服宜小智 · 右手挥动打招呼 · 可 3D 打印摆件"),
    "pose_hip": ("双手叉腰", "白色宇航服宜小智 · 双手叉腰自信站姿 · 可 3D 打印摆件"),
    "pose_salute": ("举手敬礼", "白色宇航服宜小智 · 举手敬礼精神站姿 · 可 3D 打印摆件"),
    "pose_wave_hy": ("招手·混元3D", "宜小智招手打招呼 · 混元3D 云端生成 · 可 3D 打印摆件"),
}

# Which axis of the file is the height. The Tripo presets were printed with
# the Z axis scaled to 100 mm, the raw Hunyuan model kept its own Y-up
# orientation.
_PRESET_UP_AXIS = {
    "pose_wave": "z",
    "pose_hip": "z",
    "pose_salute": "z",
    "pose_wave_hy": "y",
}


@app.get("/api/presets/models")
def list_preset_models():
    if not os.path.isdir(_PRESET_ROOT):
        return {"items": []}
    items = []
    for name in sorted(os.listdir(_PRESET_ROOT)):
        d = os.path.join(_PRESET_ROOT, name)
        if not os.path.isdir(d):
            continue
        glb = os.path.join(d, "model.glb")
        if not os.path.isfile(glb):
            continue
        stl = os.path.join(d, "model.stl")
        thumb = os.path.join(d, "thumb.png")
        label, desc = _PRESET_NAMES.get(name, (name, "宜小智 3D 预制模型"))
        items.append({
            "id": name,
            "name": label,
            "desc": desc,
            "thumbUrl": f"/api/presets/{name}/thumb.png" if os.path.isfile(thumb) else None,
            "glbUrl": f"/api/presets/{name}/model.glb",
            "stlUrl": f"/api/presets/{name}/model.stl" if os.path.isfile(stl) else None,
            "upAxis": _PRESET_UP_AXIS.get(name, "z"),
        })
    return {"items": items}


@app.get("/api/presets/{name}/{rest:path}")
def serve_preset_file(name: str, rest: str):
    base = os.path.realpath(_PRESET_ROOT)
    p = os.path.realpath(os.path.join(base, name, rest))
    if not p.startswith(base) or not os.path.isfile(p):
        raise HTTPException(404)
    ext = os.path.splitext(p)[1].lower()
    mt = EXT_MIME.get(ext, "application/octet-stream")
    return FileResponse(p, media_type=mt)
@app.on_event("startup")
def _startup():
    # Mirror the packaged laser-card back templates into the runtime data dir
    # so a fresh clone can cut a card right away.
    try:
        laser_card.ensure_templates(DATA)
    except Exception:
        traceback.print_exc()

    # The local diffusion stacks (SD 1.5, TripoSR, Hunyuan3D-2 mini) are
    # several GB of VRAM/RAM each and they are only fallback engines: the
    # default path is the cloud image + cloud 3D chain.  Preloading them on
    # every start made the app slow to boot and could starve the machine of
    # memory, so we only report what is installed and let each engine load
    # itself the first time a request actually needs it.
    def report_engines():
        try:
            if sd_client.is_available():
                print("[startup] SD 1.5 available (loads on first use)", flush=True)
            else:
                print("[startup] SD 1.5 unavailable - using cloud image chain "
                      "(local checkpoint or torch missing)", flush=True)
            if triposr_runner.is_available():
                print("[startup] TripoSR available (loads on first use)", flush=True)
            else:
                print("[startup] TripoSR unavailable - using cloud/cartoon chain "
                      "(model weights or torch missing)", flush=True)
            if hunyuan_runner.is_available():
                print("[startup] Hunyuan3D-2 mini available (loads on first use)", flush=True)
            else:
                # 打印真实原因（模型权重缺失 / 无 CUDA / torch 缺失），
                # 原来的 "torch missing" 文案会误导排查方向。
                print(f"[startup] Hunyuan3D-2 mini unavailable "
                      f"({hunyuan_runner.get_status().get('reason', 'unknown')}) "
                      f"- using Tripo3D/cartoon chain", flush=True)
            print(f"[startup] jojo-image key loaded: {bool(api_image.JOJO_KEY)}", flush=True)
            print(f"[startup] AIXJ image keys: {len(api_image.AIXJ_IMAGE_KEYS)}", flush=True)
            print(f"[startup] LLM keys: {llm_client.key_counts()}", flush=True)
        except Exception:
            traceback.print_exc()
    threading.Thread(target=report_engines, daemon=True).start()
# Frontend
if os.path.isdir(FRONTEND):
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

