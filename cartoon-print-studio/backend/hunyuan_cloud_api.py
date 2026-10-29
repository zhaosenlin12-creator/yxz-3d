"""Tencent Cloud Hunyuan3D (混元生3D 专业版) client for Cartoon Print Studio.

Fallback engine between Tripo3D (primary) and local TripoSR painting:
- submit an image to SubmitHunyuanTo3DProJob (PBR on, Normal geometry)
- poll QueryHunyuanTo3DProJob until DONE
- download the result zip, pick the .glb, clean/scale for print.

Auth: Tencent Cloud API 3.0 signature (TC3-HMAC-SHA256) with
hunyuan3d-secret-id / hunyuan3d-secret-key from keys.txt.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_HOST = "ai3d.tencentcloudapi.com"
_VERSION = "2025-05-13"
_REGION = "ap-guangzhou"
_SERVICE = "ai3d"

_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEYFILE = os.path.join(_ROOT, "keys.txt")


def _load_keys() -> Dict[str, str]:
    secret_id = os.environ.get("HUNYUAN3D_SECRET_ID", "").strip()
    secret_key = os.environ.get("HUNYUAN3D_SECRET_KEY", "").strip()
    if secret_id and secret_key:
        return {"id": secret_id, "key": secret_key}
    if os.path.isfile(_KEYFILE):
        with open(_KEYFILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("hunyuan3d-secret-id:"):
                    v = line.split(":", 1)[1].strip()
                    if v and "请填入" not in v:
                        secret_id = v
                elif line.startswith("hunyuan3d-secret-key:"):
                    v = line.split(":", 1)[1].strip()
                    if v and "请填入" not in v:
                        secret_key = v
    return {"id": secret_id, "key": secret_key}


def health() -> Dict[str, Any]:
    keys = _load_keys()
    return {
        "key_loaded": bool(keys["id"] and keys["key"]),
        "secret_id_preview": (keys["id"][:6] + "..." + keys["id"][-4:]) if keys["id"] else "",
        "host": _HOST,
        "version": _VERSION,
        "region": _REGION,
    }


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign(action: str, payload: Dict[str, Any], *, timeout: float = 15.0) -> Any:
    """Sign & POST a Tencent Cloud API 3.0 JSON request, return parsed response."""
    keys = _load_keys()
    if not keys["id"] or not keys["key"]:
        raise RuntimeError("hunyuan3d keys missing in keys.txt (hunyuan3d-secret-id / -key)")

    now = datetime.now(timezone.utc)
    timestamp = str(int(now.timestamp()))
    date = now.strftime("%Y-%m-%d")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    payload_hash = hashlib.sha256(body).hexdigest()

    canonical_uri = "/"
    canonical_query = ""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "host": _HOST,
        "x-tc-action": action.lower(),
    }
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers.items()))
    signed_headers = ";".join(sorted(headers.keys()))
    canonical_request = (
        "POST\n" + canonical_uri + "\n" + canonical_query + "\n"
        + canonical_headers + "\n" + signed_headers + "\n" + payload_hash
    )

    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n" + timestamp + "\n" + credential_scope + "\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )
    secret_date = _hmac(("TC3" + keys["key"]).encode("utf-8"), date)
    secret_service = _hmac(secret_date, _SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        "TC3-HMAC-SHA256 Credential=" + keys["id"] + "/" + credential_scope
        + ", SignedHeaders=" + signed_headers + ", Signature=" + signature
    )

    req = urllib.request.Request(
        "https://" + _HOST + "/",
        data=body,
        method="POST",
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": _HOST,
            "X-TC-Action": action,
            "X-TC-Timestamp": timestamp,
            "X-TC-Version": _VERSION,
            "X-TC-Region": _REGION,
        },
    )
    # The handshake to Tencent Cloud now and then times out or the name
    # server does not answer for a moment.  Both are over in a second or
    # two, and neither means the job was rejected, so the call is worth
    # repeating before the 3D chain gives up on this engine.
    last_err: Optional[BaseException] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read().decode("utf-8")
            try:
                import provider_health
                provider_health.report_success("hunyuan3d")
            except Exception:
                pass
            break
        except urllib.error.HTTPError:
            try:
                import provider_health
                provider_health.report_failure(
                    "hunyuan3d", "server", f"HTTP error on {action}")
            except Exception:
                pass
            raise
        except Exception as exc:  # URLError, socket timeout, DNS hiccup
            last_err = exc
            print(
                f"[hunyuan3d] {action} attempt {attempt + 1}/3 "
                f"{type(exc).__name__}: {str(exc)[:120]}",
                flush=True,
            )
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    else:
        try:
            import provider_health
            provider_health.report_failure(
                "hunyuan3d", "network", f"{action}: {last_err}")
        except Exception:
            pass
        raise RuntimeError(f"hunyuan3d {action} 网络不通：{last_err}")
    resp = json.loads(data)
    response = resp.get("Response", resp)
    if response.get("Error"):
        raise RuntimeError(f"hunyuan3d {action} error: {response['Error']}")
    return response


def submit_image_to_model(image_path: str, *,
                          model: str = "3.1",
                          enable_pbr: bool = True,
                          face_count: int = 500000,
                          timeout: float = 20.0) -> str:
    """Upload an image (base64) and submit a professional 3D generation job. Returns JobId."""
    with open(image_path, "rb") as f:
        raw = f.read()
    size_mb = len(raw) / 1024 / 1024
    if size_mb > 4.5:
        raise RuntimeError(f"hunyuan3d image too large: {size_mb:.1f}MB (base64 limit ~6MB)")
    image_b64 = base64.b64encode(raw).decode("ascii")
    payload: Dict[str, Any] = {
        "Model": model,
        "ImageBase64": image_b64,
        "GenerateType": "Normal",
        "EnablePBR": enable_pbr,
        "FaceCount": face_count,
    }
    resp = _sign("SubmitHunyuanTo3DProJob", payload, timeout=timeout)
    job_id = resp.get("JobId")
    if not job_id:
        raise RuntimeError(f"hunyuan3d submit returned no JobId: {resp}")
    print(f"[hunyuan3d] submitted job {job_id} model={model} pbr={enable_pbr} image={size_mb:.1f}MB", flush=True)
    return job_id


def query_job(job_id: str, *, timeout: float = 15.0) -> Dict[str, Any]:
    return _sign("QueryHunyuanTo3DProJob", {"JobId": job_id}, timeout=timeout)


def poll_until_done(job_id: str, *,
                    poll_interval: float = 5.0,
                    max_wait: float = 480.0,
                    on_poll=None) -> Dict[str, Any]:
    """Poll the job until DONE/FAIL. Returns the final response dict."""
    deadline = time.time() + max_wait
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        try:
            resp = query_job(job_id)
        except Exception as e:
            print(f"[hunyuan3d] poll error for {job_id}: {e}", flush=True)
            time.sleep(poll_interval * 2)
            continue
        status = str(resp.get("Status", "")).upper()
        last = resp
        if on_poll:
            try:
                on_poll(resp)
            except Exception:
                pass
        print(f"[hunyuan3d] {job_id} status={status} credits={resp.get('ResultCreditConsumed')}", flush=True)
        if status == "DONE":
            return resp
        if status in ("FAIL", "FAILED"):
            raise RuntimeError(f"hunyuan3d job {job_id} failed: {resp.get('ErrorMessage') or resp.get('ErrorCode') or resp}")
        time.sleep(poll_interval)
    raise TimeoutError(f"hunyuan3d job {job_id} did not finish in {max_wait}s; last={last}")


def _download(url: str, out_path: str, timeout: float = 120.0) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        with open(out_path, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    return os.path.getsize(out_path)


def process_glb(glb_path: str, out_dir: str, *, target_height_mm: float = 70.0) -> Dict[str, Any]:
    """Turn the cloud model into a viewer GLB and a printable body.

    The cloud engines hand the figurine back as a couple of hundred closed
    shells - a helmet, a torso, an arm, a base - plus a pile of loose
    fragments.  They overlap each other and none of them is watertight on
    its own, so:

    - the viewer gets the shells with their texture, decimation applied, so
      the robot shows up whole in the browser;
    - the printer gets one solid body, rebuilt from the volume of those
      shells, because a slicer cannot cut a pile of overlapping shells.
    """
    import trimesh
    import mesh_postprocess
    mesh = trimesh.load(glb_path, force="mesh")
    # Hunyuan3D outputs Y-up; convert to Z-up with a flat bottom for slicing.
    mesh = mesh_postprocess.align_up_axis(mesh, source_up="y")
    largest = float(max(mesh.extents))
    if largest > 0:
        mesh.apply_scale(mesh_postprocess.PRINT_LENGTH_MM / largest)
    # Keep every real body of the figurine, drop the loose fragments.
    mesh = mesh_postprocess.keep_significant_shells(mesh)

    # --- the model the browser shows: the painted shells themselves, so the
    # robot keeps every detail the cloud engine gave us
    viewer = mesh_postprocess.optimize_for_web(mesh, target_faces=120000, texture_size=2048)

    # --- the body the printer cuts
    solid = mesh_postprocess.solidify_mesh(mesh, pitch_mm=0.5)
    # The requested size is the standing height. After the Y-up -> Z-up
    # conversion the height is the Z extent, which is the same rule the
    # Tripo path uses. Scaling by the longest side instead ignored the
    # parameter completely and always produced a 100mm model.
    extents = solid.extents
    height = float(extents[2]) if len(extents) >= 3 else 0.0
    target = float(target_height_mm or 0)
    if target > 0 and height > 0:
        scale = target / height
    elif max(extents) > 0:
        scale = 100.0 / max(extents)
    else:
        scale = 1.0
    if scale > 0:
        solid.apply_scale(scale)
        # The preview shows the same model, so it has to end up at the same
        # size as the file that goes to the printer.
        viewer.apply_scale(scale)
    # The debris filter runs on the 100 mm scale that clean_for_print uses.
    # Scaling down afterwards can leave a speck of a few triangles behind,
    # and a stray loose triangle is enough to make a slicer report the model
    # as not watertight. Drop those once more, now that the mesh has its
    # final size.
    solid = _drop_print_debris(solid)
    # Lower to z=0 for a stable print bed
    bbox = solid.bounds
    if bbox[0][2] < 0:
        solid.apply_translation([0, 0, -bbox[0][2]])
    viewer_bbox = viewer.bounds
    if viewer_bbox[0][2] < 0:
        viewer.apply_translation([0, 0, -viewer_bbox[0][2]])
    glb_out = os.path.join(out_dir, "mesh.glb")
    mesh_postprocess.export_atomic(viewer, glb_out)
    obj_out = os.path.join(out_dir, "mesh.obj")
    stl_out = os.path.join(out_dir, "mesh.stl")
    mesh_postprocess.export_atomic(solid, obj_out)
    mesh_postprocess.export_atomic(solid, stl_out)
    return {
        "glb": glb_out,
        "obj": obj_out,
        "stl": stl_out,
        "vertices": len(solid.vertices),
        "faces": len(solid.faces),
        "extents_mm": solid.extents.tolist(),
        "viewer_faces": len(viewer.faces),
        "watertight": bool(solid.is_watertight),
    }


def _drop_print_debris(mesh, *, min_faces: int = 8):
    """Remove tiny loose fragments from a freshly scaled print mesh."""
    import numpy as np
    import trimesh

    if mesh is None or len(mesh.faces) < min_faces:
        return mesh
    try:
        from trimesh.graph import connected_components
        groups = connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
    except Exception as _e:
        print(f"[hunyuan] debris pass skipped: {_e}", flush=True)
        return mesh

    groups = [np.asarray(group, dtype=np.int64) for group in groups]
    if len(groups) <= 1:
        return mesh

    groups.sort(key=len, reverse=True)
    keep = groups[0]
    if len(keep) == len(mesh.faces):
        return mesh
    try:
        cleaned = mesh.submesh([keep], append=True, repair=False)
    except Exception as _e:
        print(f"[hunyuan] debris pass failed: {_e}", flush=True)
        return mesh
    print(f"[hunyuan] dropped {len(groups) - 1} loose fragment(s) "
          f"({len(mesh.faces) - len(cleaned.faces)} faces)", flush=True)
    return cleaned


def image_to_model(image_path: str, out_dir: str, *,
                   model: str = "3.1",
                   enable_pbr: bool = True,
                   face_count: int = 500000,
                   max_wait: float = 480.0,
                   target_height_mm: float = 70.0,
                   on_poll=None) -> Dict[str, Any]:
    """Full pipeline: submit -> poll -> download -> pick glb -> process for print."""
    import shutil
    import zipfile
    os.makedirs(out_dir, exist_ok=True)
    job_id = submit_image_to_model(
        image_path, model=model, enable_pbr=enable_pbr, face_count=face_count,
    )
    resp = poll_until_done(job_id, max_wait=max_wait, on_poll=on_poll)

    files3d = resp.get("ResultFile3Ds") or []
    if not files3d:
        raise RuntimeError(f"hunyuan3d DONE but no ResultFile3Ds: {resp}")
    # Prefer GLB entry; fall back to first entry.
    glb_entry = next((f for f in files3d if str(f.get("Type", "")).upper() == "GLB"), files3d[0])
    url = glb_entry.get("Url")
    if not url:
        raise RuntimeError(f"hunyuan3d result has no Url: {glb_entry}")
    zip_path = os.path.join(out_dir, "hunyuan3d_result.zip")
    print(f"[hunyuan3d] downloading result zip from COS ...", flush=True)
    size = _download(url, zip_path)
    print(f"[hunyuan3d] downloaded {size} bytes", flush=True)

    glb_src = None
    with open(zip_path, "rb") as fh:
        magic = fh.read(4)
    if magic[:2] == b"PK":
        # 结果是 zip 包：解包后取 .glb
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            for n in names:
                if n.lower().endswith(".glb"):
                    glb_src = os.path.join(out_dir, "result" + os.path.splitext(n)[1])
                    with open(glb_src, "wb") as f:
                        f.write(z.read(n))
                    break
            if glb_src is None:
                # extract everything and look for a glb
                z.extractall(out_dir)
                for n in names:
                    if n.lower().endswith(".glb"):
                        glb_src = os.path.join(out_dir, n)
                        break
    elif magic == b"glTF":
        # 部分 COS 链接直接分发 glTF 二进制而不是 zip，无需解包
        glb_src = os.path.join(out_dir, "result.glb")
        if os.path.abspath(glb_src) != os.path.abspath(zip_path):
            shutil.move(zip_path, glb_src)
    else:
        raise RuntimeError(f"hunyuan3d 结果文件格式无法识别 (magic={magic!r})")
    if glb_src is None:
        raise RuntimeError(f"hunyuan3d 结果中没有 .glb 文件")
    info = process_glb(glb_src, out_dir, target_height_mm=target_height_mm)
    info["job_id"] = job_id
    info["credits_consumed"] = resp.get("ResultCreditConsumed")
    info["engine"] = "hunyuan3d-cloud"
    return info
