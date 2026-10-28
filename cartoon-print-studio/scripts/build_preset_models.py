# -*- coding: utf-8 -*-
"""Rebuild the 宜小智 preset printable models from the real character renders.

Why this script exists
----------------------
``presets/models/*/model.glb`` used to ship a placeholder avatar (the public
VRM sample) instead of 宜小智, so opening "宜小智预制 3D 模型" showed the wrong
character.  The renders under ``presets/images`` are the real character, so we

  1. ask the image service to strip the floating halo / stars (they merge
     into the head during image-to-3D and split the helmet),
  2. push the clean render through the very same Tencent Hunyuan3D pipeline
     the app uses for user models,
  3. copy the printable mesh into ``presets/models/<pose>/``.

Usage
-----
    python cartoon-print-studio/scripts/build_preset_models.py --stage images
    python cartoon-print-studio/scripts/build_preset_models.py --stage models
    python cartoon-print-studio/scripts/build_preset_models.py --stage all
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
REPO_ROOT = SCRIPT_DIR.parent.parent

sys.path.insert(0, str(BACKEND_DIR))

DATA_ROOT = Path(os.environ.get("CARTOON_ROOT") or str(REPO_ROOT / "cartoon-print-studio" / "data"))
IMAGE_DIR = REPO_ROOT / "presets" / "images"
BUILD_DIR = REPO_ROOT / "presets" / "build"
MODEL_DIR = REPO_ROOT / "presets" / "models"
API_BASE = os.environ.get("YXZ_PRINT_API", "http://127.0.0.1:8000").rstrip("/")

POSES = ["pose_wave", "pose_hip", "pose_salute"]

CLEAN_INSTRUCTION = (
    "去掉角色头顶上方的光环和两颗星星，只保留机器人本身。"
    "保持机器人的外形、白色宇航服、蓝色配色、姿态、光影和白色背景完全不变，"
    "画面构图与角色位置保持原样，不要新增任何元素。"
)


def _log(message: str) -> None:
    print(f"[build-presets] {message}", flush=True)


def clean_source(pose: str) -> Path:
    """Return a halo-free render for one pose, asking the image service once."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    target = BUILD_DIR / f"{pose}_clean.png"
    if target.is_file():
        return target

    source = IMAGE_DIR / f"{pose}.png"
    if not source.is_file():
        raise FileNotFoundError(f"缺少角色渲染图：{source}")

    import api_image

    _log(f"{pose}: 正在让 AI 去掉光环/星星 ...")
    blob, tag = api_image.refine_preview(source.read_bytes(), CLEAN_INSTRUCTION, sid=f"preset_{pose}")
    target.write_bytes(blob)
    _log(f"{pose}: 清理完成 ({tag}) -> {target}")
    return target


def _prepare_session(pose: str, image: Path) -> str:
    sid = f"yxzpreset_{pose}"
    previews = DATA_ROOT / sid / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, previews / "img_0.png")
    return sid


def build_model(pose: str, image: Path, *, face_count: int = 200000, target_faces: int = 60000,
                enable_pbr: bool = False) -> None:
    """Run the cloud image-to-3D pipeline and publish a printable model.

    PBR is off by default: the PBR export bakes a fully metallic, zero
    roughness material into the albedo, which renders the figurine like
    polished chrome.  The plain textured export keeps the painted plastic
    look of the design and is also smaller and faster to build.
    """
    import hunyuan_cloud_api as hyc
    import mesh_postprocess
    import trimesh

    sid = _prepare_session(pose, image)
    out_dir = DATA_ROOT / sid / "model"
    _log(f"{pose}: 提交混元3D 云端生成（session={sid}, pbr={enable_pbr}）...")
    info = hyc.image_to_model(
        str(image),
        str(out_dir),
        model="3.1",
        enable_pbr=enable_pbr,
        face_count=face_count,
        max_wait=600.0,
        target_height_mm=100.0,
    )
    _log(f"{pose}: 云端完成 faces={info.get('faces')} job={info.get('job_id')}")

    # The raw cloud answer is ~35 MB with a 4K texture set; shrink it so the
    # browser preview loads fast and the repository stays a sane size.
    raw_glb = Path(info["glb"])
    mesh = trimesh.load(str(raw_glb), force="mesh")
    mesh = mesh_postprocess.optimize_for_web(mesh, target_faces=target_faces, texture_size=1024)
    mesh = mesh_postprocess.make_matte_material(mesh)
    _log(f"{pose}: 优化后 faces={len(mesh.faces)}")

    publish_dir = MODEL_DIR / pose
    publish_dir.mkdir(parents=True, exist_ok=True)
    mesh.export(str(publish_dir / "model.glb"))
    mesh.export(str(publish_dir / "model.stl"))
    # The thumbnail is the halo-free render the model was actually built
    # from, so the gallery and the 3D preview show the same character.
    thumb = BUILD_DIR / f"{pose}_clean.png"
    if not thumb.is_file():
        thumb = IMAGE_DIR / f"{pose}.png"
    if thumb.is_file():
        shutil.copyfile(thumb, publish_dir / "thumb.png")
    for produced in ("mesh.glb", "mesh.stl"):
        source = Path(out_dir) / produced
        if source.is_file():
            size_mb = source.stat().st_size / 1024 / 1024
            _log(f"{pose}: {produced} {size_mb:.1f} MB")
    _log(f"{pose}: 已写入 {publish_dir}")


def retouch_model(pose: str) -> None:
    """Re-materialise an already published model, without a cloud run.

    The cloud export ships a chrome material; flattening it into matte
    plastic only touches the material, so the published mesh can be fixed in
    place instead of paying for another image-to-3D job.
    """
    import mesh_postprocess
    import trimesh

    publish_dir = MODEL_DIR / pose
    glb_path = publish_dir / "model.glb"
    if not glb_path.is_file():
        raise FileNotFoundError(f"缺少已发布的模型：{glb_path}")

    _log(f"{pose}: 正在重新调整材质 ...")
    mesh = trimesh.load(str(glb_path), force="mesh")
    mesh = mesh_postprocess.make_matte_material(mesh)
    mesh.export(str(glb_path))
    mesh.export(str(publish_dir / "model.stl"))

    thumb = BUILD_DIR / f"{pose}_clean.png"
    if not thumb.is_file():
        thumb = IMAGE_DIR / f"{pose}.png"
    if thumb.is_file():
        shutil.copyfile(thumb, publish_dir / "thumb.png")
    _log(f"{pose}: 材质已更新 -> {glb_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the 宜小智 preset 3D models")
    parser.add_argument("--stage", choices=["images", "models", "retouch", "all"], default="all")
    parser.add_argument("--poses", nargs="*", default=POSES)
    parser.add_argument("--pbr", action="store_true",
                        help="ask the cloud engine for a PBR export (chrome-like material)")
    args = parser.parse_args()

    for pose in args.poses:
        if args.stage == "retouch":
            retouch_model(pose)
            continue
        image = clean_source(pose)
        if args.stage == "images":
            continue
        build_model(pose, image, enable_pbr=args.pbr)
    _log("全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())