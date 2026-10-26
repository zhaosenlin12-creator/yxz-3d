"""Persistent task records for multi-view Gaussian Splat reconstruction.

This module deliberately does not synthesize a fake 3DGS result.  It stores a
student's capture set, assesses whether it is usable, and optionally hands it
to a separately deployed GPU worker through a small HTTP contract.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
SPLAT_EXTENSIONS = {".ply", ".splat", ".sog", ".spz"}
MAX_CAPTURE_BYTES = 80 * 1024 * 1024
MAX_ASSET_BYTES = 1024 * 1024 * 1024


def safe_name(name: str, fallback: str = "capture") -> str:
    base = os.path.basename(name or fallback)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base or fallback


def capture_kind(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def assess_capture(files: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    files = list(files)
    image_count = sum(item.get("kind") == "image" for item in files)
    video_count = sum(item.get("kind") == "video" for item in files)
    if image_count >= 32:
        return {"level": "READY", "score": 92, "message": "多视角数量充足，可提交真实重建"}
    if image_count >= 20:
        return {"level": "GOOD", "score": 76, "message": "可训练；建议补拍底部和背面"}
    if image_count >= 12:
        return {"level": "BASIC", "score": 58, "message": "可尝试训练；建议补到 20 张以上"}
    if video_count:
        return {"level": "VIDEO", "score": 64, "message": "视频已接收，云端会自动抽帧；建议环绕拍摄 10–30 秒"}
    return {"level": "NEEDS_MORE", "score": 0, "message": "至少上传 12 张环绕照片，或一段环绕视频"}


class SceneJobStore:
    def __init__(self, data_root: str):
        self.root = Path(data_root)

    def _dir(self, scene_id: str) -> Path:
        return self.root / scene_id

    def _meta(self, scene_id: str) -> Path:
        return self._dir(scene_id) / "scene.json"

    def create(self, title: str, capture_files: list[Dict[str, Any]]) -> Dict[str, Any]:
        scene_id = f"scene_{uuid.uuid4().hex[:12]}"
        now = int(time.time())
        quality = assess_capture(capture_files)
        record = {
            "sceneId": scene_id,
            "title": title.strip()[:80] or "我的真实场景",
            "status": "CAPTURE_READY" if quality["level"] != "NEEDS_MORE" else "NEEDS_MORE_CAPTURE",
            "createdAt": now,
            "updatedAt": now,
            "captures": capture_files,
            "quality": quality,
            "cloud": {"provider": "nerfstudio-worker", "remoteJobId": None, "statusUrl": None},
            "result": None,
            "message": quality["message"],
        }
        self.save(record)
        return record

    def load(self, scene_id: str) -> Dict[str, Any] | None:
        if not re.fullmatch(r"scene_[a-f0-9]{12}", scene_id or ""):
            return None
        path = self._meta(scene_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, record: Dict[str, Any]) -> None:
        scene_id = record["sceneId"]
        directory = self._dir(scene_id)
        directory.mkdir(parents=True, exist_ok=True)
        record["updatedAt"] = int(time.time())
        self._meta(scene_id).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def public(self, record: Dict[str, Any]) -> Dict[str, Any]:
        result = record.get("result")
        captures = [
            {key: item[key] for key in ("name", "kind", "size", "contentType") if key in item}
            | {"url": f"/api/data/{record['sceneId']}/{item['path']}"}
            for item in record.get("captures", [])
        ]
        return {
            "sceneId": record["sceneId"],
            "title": record["title"],
            "status": record["status"],
            "createdAt": record["createdAt"],
            "updatedAt": record["updatedAt"],
            "captures": captures,
            "quality": record.get("quality"),
            "message": record.get("message", ""),
            "cloud": record.get("cloud", {}),
            "result": result,
            "captureManifestUrl": f"/api/scenes/{record['sceneId']}/manifest",
        }


def trainer_configured() -> bool:
    return bool(os.environ.get("SCENE_TRAINER_URL") or local_trainer_configured())


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _tool_path(env_name: str, fallback: Path) -> Path:
    value = os.environ.get(env_name, "").strip()
    if value:
        return Path(value)
    return fallback


def local_trainer_configured() -> bool:
    """Return whether the bundled offline Brush + COLMAP trainer is usable."""
    if os.environ.get("SCENE_TRAINER_MODE", "").strip().lower() != "local":
        return False
    root = _project_root()
    brush = _tool_path("SCENE_BRUSH_BIN", root / "tools" / "brush" / "app" / "brush_app.exe")
    colmap = _tool_path("SCENE_COLMAP_BIN", root / "tools" / "colmap" / "app" / "COLMAP.bat")
    return brush.is_file() and (colmap.is_file() or shutil.which("colmap")) and bool(shutil.which("ffmpeg"))


def trainer_provider() -> str:
    return "brush-local" if local_trainer_configured() else "nerfstudio-worker"


def _run_command(command: list[str], cwd: Path, log_path: Path, timeout: int = 3600) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write("$ " + " ".join(command) + "\n")
        process = subprocess.run(command, cwd=str(cwd), stdout=handle, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if process.returncode:
        raise RuntimeError(f"本地重建命令失败（退出码 {process.returncode}），可查看训练日志")


def _registered_image_count(colmap_cmd: str, model: Path, cwd: Path, log_path: Path) -> int:
    """Read COLMAP's reconstruction statistics and enforce a useful baseline."""
    command = [colmap_cmd, "model_analyzer", "--path", str(model)]
    with log_path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write("$ " + " ".join(command) + "\n")
        process = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        handle.write(process.stdout or "")
    if process.returncode:
        raise RuntimeError("COLMAP 无法读取相机轨迹；请重新拍摄有明显环绕移动的素材")
    match = re.search(r"Registered images:\s*(\d+)", process.stdout or "")
    if not match:
        raise RuntimeError("COLMAP 未返回有效相机轨迹；请重新拍摄有明显环绕移动的素材")
    return int(match.group(1))


def _local_train(record: Dict[str, Any], scene_root: Path, store: SceneJobStore) -> None:
    """Extract a capture, solve poses with COLMAP, then train Brush."""
    scene_root = Path(scene_root)
    work = scene_root / "scene" / "local-brush"
    images = work / "images"
    database = work / "database.db"
    sparse = work / "sparse"
    result_dir = work / "result"
    log_path = work / "training.log"
    images.mkdir(parents=True, exist_ok=True)
    sparse.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法从视频抽帧")
    # Reuse existing images on retry; this keeps a second submission quick.
    if not any(images.glob("*.jpg")):
        captures = record.get("captures", [])
        for item in captures:
            source = scene_root / item.get("path", "")
            if item.get("kind") == "image":
                shutil.copy2(source, images / safe_name(item.get("name", "capture.jpg")))
            elif item.get("kind") == "video":
                _run_command([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", "fps=6,scale=1280:-2", "-q:v", "3", str(images / "frame_%05d.jpg")], scene_root, log_path, 900)
    if not any(images.glob("*.jpg")):
        raise RuntimeError("没有可用于训练的图片")
    colmap = _tool_path("SCENE_COLMAP_BIN", _project_root() / "tools" / "colmap" / "app" / "COLMAP.bat")
    colmap_cmd = str(colmap) if colmap.is_file() else (shutil.which("colmap") or "colmap")
    common = ["--database_path", str(database)]
    _run_command([colmap_cmd, "feature_extractor", *common, "--image_path", str(images), "--ImageReader.single_camera", "1", "--ImageReader.camera_model", "OPENCV"], scene_root, log_path, 900)
    _run_command([colmap_cmd, "exhaustive_matcher", *common], scene_root, log_path, 900)
    _run_command([colmap_cmd, "mapper", "--database_path", str(database), "--image_path", str(images), "--output_path", str(sparse), "--Mapper.min_model_size", "2"], scene_root, log_path, 1800)
    models = sorted([path for path in sparse.iterdir() if path.is_dir() and (path / "images.bin").is_file()], key=lambda path: path.name)
    if not models:
        raise RuntimeError("COLMAP 没有恢复出相机轨迹；请拍摄有明显环绕移动的 20–60 秒视频")
    model_stats = [
        (candidate, _registered_image_count(colmap_cmd, candidate, scene_root, log_path))
        for candidate in models
    ]
    model, registered = max(model_stats, key=lambda item: item[1])
    minimum = max(3, int(os.environ.get("SCENE_MIN_REGISTERED_IMAGES", "8")))
    if registered < minimum:
        raise RuntimeError(
            f"只恢复出 {registered} 个有效视角，暂不生成低质量场景；请使用 10–30 秒环绕视频或 20–60 张照片"
        )
    # Brush expects sparse/0 next to images. Keep the selected reconstruction deterministic.
    target_model = sparse / "0"
    if model != target_model:
        if target_model.exists():
            shutil.rmtree(target_model)
        model.rename(target_model)
    brush = _tool_path("SCENE_BRUSH_BIN", _project_root() / "tools" / "brush" / "app" / "brush_app.exe")
    _run_command([str(brush), str(work), "--total-steps", os.environ.get("SCENE_BRUSH_STEPS", "3000"), "--max-resolution", "1280", "--max-splats", "500000", "--export-path", str(result_dir), "--export-name", "scene.ply", "--export-every", os.environ.get("SCENE_BRUSH_STEPS", "3000")], scene_root, log_path, 7200)
    asset = result_dir / "scene.ply"
    if not asset.is_file():
        candidates = sorted(result_dir.glob("*.ply"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("Brush 训练结束但没有导出 PLY 文件")
        asset = candidates[0]
    rel_asset = asset.relative_to(scene_root).as_posix()
    asset_url = f"/api/data/{record['sceneId']}/{rel_asset}"
    viewer_url = f"/vendor/supersplat/index.html?content={asset_url}&settings=/vendor/supersplat/settings.json&lang=zh-CN&webgl&noui"
    record["status"] = "READY"
    record["message"] = "本地 Brush 场景已经可以探索"
    record["result"] = {"name": asset.name, "format": "ply", "size": asset.stat().st_size, "assetUrl": asset_url, "viewerUrl": viewer_url}
    record["cloud"] = {"provider": "brush-local", "remoteJobId": record.get("cloud", {}).get("remoteJobId"), "statusUrl": f"/api/scenes/{record['sceneId']}"}
    store.save(record)


def start_local_training(record: Dict[str, Any], scene_root: str, store: SceneJobStore) -> Dict[str, Any]:
    job_id = f"local_{uuid.uuid4().hex[:12]}"
    record["cloud"] = {"provider": "brush-local", "remoteJobId": job_id, "statusUrl": f"/api/scenes/{record['sceneId']}"}

    # Persist the queued state before starting the worker.  This avoids a fast
    # local run being overwritten by the request handler's final save.
    record["status"] = "CLOUD_QUEUED"
    record["message"] = "本地 Brush 训练已开始"
    store.save(record)

    def worker() -> None:
        try:
            _local_train(record, Path(scene_root), store)
        except Exception as exc:  # keep the UI pollable even when a tool fails
            message = str(exc).strip() or "本地重建失败"
            record["status"] = "FAILED"
            record["message"] = message[:240]
            record["cloud"] = {
                "provider": "brush-local",
                "remoteJobId": job_id,
                "statusUrl": f"/api/scenes/{record['sceneId']}",
            }
            log_path = Path(scene_root) / "scene" / "local-brush" / "training.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8", errors="replace") as handle:
                    handle.write("\n[local-trainer-error] " + message + "\n")
                    traceback.print_exc(file=handle)
            except OSError:
                pass
            store.save(record)

    thread = threading.Thread(target=worker, daemon=True, name=f"brush-{record['sceneId']}")
    thread.start()
    return {"remoteJobId": job_id, "statusUrl": f"/api/scenes/{record['sceneId']}", "message": "本地 Brush 训练已开始"}


def submit_to_trainer(record: Dict[str, Any], scene_root: Path) -> Dict[str, Any]:
    """Submit capture files to a compatible cloud worker, if configured.

    Worker request contract: multipart POST with `manifest` JSON and repeated
    `captures` file fields. Response must contain `remoteJobId`; optional
    `statusUrl` and `message` are persisted verbatim as data, never rendered
    as HTML.
    """
    endpoint = os.environ.get("SCENE_TRAINER_URL", "").strip()
    if not endpoint:
        raise RuntimeError("未配置 SCENE_TRAINER_URL；可先导出采集清单，再部署 Nerfstudio/gsplat GPU worker")
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("云端提交依赖 requests 不可用") from exc

    captures = []
    files = []
    scene_root = Path(scene_root)
    try:
        for item in record.get("captures", []):
            path = scene_root / item["path"]
            if not path.is_file():
                continue
            captures.append(item)
            files.append(("captures", (item["name"], path.open("rb"), item.get("contentType") or "application/octet-stream")))
        payload = {"sceneId": record["sceneId"], "title": record["title"], "captures": captures}
        response = requests.post(
            endpoint,
            data={"manifest": json.dumps(payload, ensure_ascii=False)},
            files=files,
            headers={"Authorization": f"Bearer {os.environ.get('SCENE_TRAINER_TOKEN', '')}"} if os.environ.get("SCENE_TRAINER_TOKEN") else {},
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"云训练器返回 HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("remoteJobId"), str):
            raise RuntimeError("云训练器响应缺少 remoteJobId")
        return data
    finally:
        for _, (_, handle, _) in files:
            handle.close()
