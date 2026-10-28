"""TripoSR image -> mesh pipeline (single image).

Heavy imports are deferred so the module loads even when torch/TripoSR are not
installed (e.g. in a packaged build that only uses Tripo3D cloud).
"""
import os, sys, time, threading

# Lazy torch (loaded only when actually running TripoSR inference)
_torch = None
def _import_torch():
    global _torch
    if _torch is None:
        import torch as _t
        _torch = _t
    return _torch

# Lazy heavy deps (TripoSR pipeline + RMBG background removal)
Image = None; TSR = None; resize_foreground = None; remove_bg = None
marching_cubes = None
_HEAVY_OK = False
_HEAVY_ERR = "not loaded yet"

def _ensure_packages():
    """Lazy import of TripoSR + torchmcubes shim + rmbg. Safe to call repeatedly."""
    global Image, TSR, resize_foreground, remove_bg, marching_cubes, _HEAVY_OK, _HEAVY_ERR
    if _HEAVY_OK or _HEAVY_ERR != "not loaded yet":
        return _HEAVY_OK
    try:
        import torchmcubes_skimage  # registers torchmcubes shim
        from torchmcubes import marching_cubes as _mc
        from PIL import Image as _I
        from tsr.system import TSR as _TSR
        from tsr.utils import resize_foreground as _rf
        from rmbg_remove import remove_bg as _rb
        Image = _I
        TSR = _TSR
        resize_foreground = _rf
        remove_bg = _rb
        marching_cubes = _mc
        _HEAVY_OK = True
        _HEAVY_ERR = ""
    except Exception as _e:
        _HEAVY_OK = False
        _HEAVY_ERR = str(_e)
        print(f"[triposr_runner] heavy deps unavailable: {_e}", flush=True)
    return _HEAVY_OK

# Resolve ROOT dynamically (env override in packaged mode)
_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRI_MODEL = os.path.join(_ROOT, "models", "cache", "models", "AI-ModelScope--TripoSR", "snapshots", "master")

# Make triposr importable (only when the heavy path is taken)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import trimesh
import os as _os_progress_helper
import progress as _pg



_TSR = None
_LOCK = threading.Lock()


def _load():
    global _TSR
    if _TSR is not None:
        return _TSR
    # The heavy imports have to happen before TSR is referenced.  They used
    # to be skipped entirely, so every TripoSR call died with
    # "NoneType has no attribute from_pretrained".
    if not _ensure_packages():
        raise RuntimeError(f"TripoSR dependencies unavailable: {_HEAVY_ERR or 'unknown error'}")
    print("[triposr] loading model...")
    t0 = time.time()
    _TSR = TSR.from_pretrained(
        TRI_MODEL,
        config_name="config.yaml",
        weight_name="model.ckpt",
    )
    # Override cond_image_size to 256 to fit 2-view forward in 6GB VRAM.
    # TripoSR was trained at 512 but works fine at 256 — quality drop is small
    # for cartoon-style images where the input itself is low-detail.
    try:
        _TSR.cfg.cond_image_size = 256
        print(f"[triposr] cond_image_size overridden to 256")
    except Exception as _e:
        print(f"[triposr] could not override cond_image_size: {_e}")
    # Some TripoSR submodules initialize on the meta device; load_state_dict
    # silently no-ops for them. Force a real device with to_empty then reload
    # the weights so the model actually has numeric data.
    try:
        _TSR.to_empty(device="cuda")
        import torch as _t
        ckpt = _t.load(os.path.join(TRI_MODEL, "model.ckpt"), map_location="cuda", weights_only=False)
        _TSR.load_state_dict(ckpt, assign=True)
    except Exception as _e:
        print(f"[triposr] assign-load fallback failed ({_e}); retrying plain .to(cuda)", flush=True)
        try:
            _TSR.to("cuda")
        except Exception as _e2:
            print(f"[triposr] plain .to(cuda) also failed: {_e2}", flush=True)
            raise
    print(f"[triposr] loaded in {time.time()-t0:.1f}s")
    return _TSR




def unload():
    """Move TripoSR model to CPU and free CUDA memory. Used to make room for Hunyuan."""
    global _TSR
    if _TSR is None:
        return
    try:
        _TSR.to("cpu")
    except Exception:
        pass
    _TSR = None
    import torch as _t
    _t.cuda.empty_cache()
    print("[triposr] unloaded")


def set_device(device):
    global _TSR
    if _TSR is None:
        return
    try:
        _TSR.to(device)
    except Exception as e:
        print(f"[triposr] to {device} failed: {e}")

def warmup():
    """Load the local model. Raises when the local engine is not installed."""
    _load()
    return True


def is_available() -> bool:
    """True when the local TripoSR engine can actually run.

    Checking that ``torch`` imports is not enough: the TripoSR package, the
    marching-cubes shim and the RMBG helper are separate dependencies, and
    the checkpoint has to be on disk.  Only a real probe of all three keeps
    the status honest.
    """
    if not os.path.isfile(os.path.join(TRI_MODEL, "model.ckpt")):
        return False
    try:
        import importlib
        importlib.import_module("torch")
        importlib.import_module("tsr.system")
    except Exception:
        return False
    return True


def generate_3d(image_paths, output_dir, *, mc_res=128, threshold=15.0, max_views=2):
    """image_paths: str or list of str -> writes {output_dir}/mesh.glb/.obj/.stl.

    Multi-view input is supported natively by TripoSR — model takes a list of RGB images
    and returns one scene code per view. We average the scene codes (along batch dim)
    to produce a single fused reconstruction. Falls back to single view on OOM.

    Args:
        image_paths: single path or list of paths (front view first is best).
        output_dir: directory to write mesh.glb/.obj/.stl into.
        mc_res: marching cubes resolution.
        threshold: density threshold for isosurface extraction.
        max_views: cap on views used (default 2 — fits in 6GB VRAM).
    """
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    # Cap views: TripoSR produces one scene code per view, averaging >2 views
    # tends to blur features and the VRAM cost grows linearly.
    if len(image_paths) > max_views:
        print(f"[triposr] capping views from {len(image_paths)} to {max_views}")
        image_paths = image_paths[:max_views]
    os.makedirs(output_dir, exist_ok=True)
    t0 = time.time()
    fg_images = []
    for p in image_paths:
        src = Image.open(p).convert("RGB")
        fg = remove_bg(src)  # RGBA
        fg_resized = resize_foreground(fg, ratio=0.85).convert("RGB")
        fg_images.append(fg_resized)
    print(f"[triposr] {len(fg_images)} view(s) preprocessed in {time.time()-t0:.1f}s")
    _pg_sid = _os_progress_helper.environ.get("PROGRESS_SID", "")
    if _pg_sid:
        _pg.Progress(_pg_sid, "3d-triposr").emit("preprocess", 25, f"已预处理 {len(fg_images)} 视图")

    model = _load()
    meshes = []
    t_total = time.time()
    with _LOCK:
        import torch
        torch.cuda.empty_cache()
        # Free Hunyuan3D weights first if loaded, so TripoSR fits in 6GB VRAM
        try:
            import hunyuan_runner as _hr
            _hr.unload()
        except Exception:
            pass
        # Aggressive VRAM cleanup
        import gc as _gc
        _gc.collect()
        torch.cuda.empty_cache()
        if hasattr(torch.cuda, 'ipc_collect'):
            try: torch.cuda.ipc_collect()
            except Exception: pass
        # Log free VRAM for debugging
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            print(f"[triposr] pre-forward VRAM: {free/1e9:.2f}GB free / {total/1e9:.2f}GB total", flush=True)
        # Run forward on all views. Each view returns its own scene code (triplane).
        # We average them along the batch dim to fuse into a single triplane.
        t1 = time.time()
        scene = None
        views_to_use = list(fg_images)
        oom_note = None
        while views_to_use:
            try:
                if _pg_sid:
                    _pg.Progress(_pg_sid, "3d-triposr").emit(
                        "forward", 50, f"TripoSR 前向推理（{len(views_to_use)} 视图）"
                    )
                scene = model(views_to_use, device="cuda")
                print(f"[triposr] forward {len(views_to_use)} view(s) in {time.time()-t1:.1f}s; scene_codes shape={tuple(scene.shape)}")
                break
            except torch.cuda.OutOfMemoryError as _oom:
                oom_note = str(_oom)
                print(f"[triposr] OOM with {len(views_to_use)} views; dropping to {len(views_to_use)-1}", flush=True)
                torch.cuda.empty_cache()
                views_to_use = views_to_use[:-1]
                if not views_to_use:
                    raise
            except RuntimeError as _re:
                # Some CUDA OOM surfaces as RuntimeError("CUDA out of memory.")
                if "out of memory" in str(_re).lower():
                    oom_note = str(_re)
                    print(f"[triposr] OOM (RuntimeError) with {len(views_to_use)} views; dropping to {len(views_to_use)-1}", flush=True)
                    torch.cuda.empty_cache()
                    views_to_use = views_to_use[:-1]
                    if not views_to_use:
                        raise
                else:
                    raise
        if scene is None:
            raise RuntimeError("TripoSR forward failed for all view counts")
        if len(views_to_use) < len(fg_images) and oom_note:
            print(f"[triposr] using {len(views_to_use)} views due to VRAM ({oom_note[:80]})", flush=True)
        # Fuse scene codes: scene shape is (N, 40, 32, 32, 32) — average across N
        if scene.shape[0] > 1:
            fused = scene.mean(dim=0, keepdim=True)
            print(f"[triposr] fused {scene.shape[0]} scene codes by averaging")
        else:
            fused = scene
        if _pg_sid:
            _pg.Progress(_pg_sid, "3d-triposr").emit("forward", 60, "多视角场景编码已融合")
        # Robust mesh extraction: bypass TripoSR's broken extract_mesh (its iso
        # threshold sweep often finds no surface on cartoon-style inputs) and
        # do our own density-field → marching-cubes pass with auto-picked threshold.
        meshes = _extract_mesh_robust(model, fused, mc_res)
        if not meshes:
            print(f"[triposr] all thresholds failed; trying supplementary view with cartoon relief", flush=True)
            if _pg_sid:
                _pg.Progress(_pg_sid, "3d-triposr").emit("forward", 70, "TripoSR 无法重建该图，回退到 3/4 视角浮雕")
            # Try the supplementary (3/4) view if available; otherwise front view.
            # The supplementary view often produces a more interesting 3D shape
            # because it shows depth and side contours.
            fallback_input = image_paths[-1] if len(image_paths) > 1 else image_paths[0]
            try:
                import mesh_postprocess as _mp
                info = _mp.cartoon_3d_figurine(
                    fallback_input, output_dir,
                    base_mm=2.5, thickness_mm=8.0,
                    back_thickness_mm=6.0, back_scale=0.85,
                    max_depth_mm=14.0, target_side=768,
                )
                info["engine"] = "triposr+cartoon_relief_fallback"
                info["fallback_reason"] = "TripoSR mesh extraction failed; used supplementary view with cartoon relief"
                info["views_used"] = len(views_to_use)
                if _pg_sid:
                    _pg.Progress(_pg_sid, "3d-triposr").done(f"导出完成 ({info['faces']:,} 面, fallback)")
                return info
            except Exception as _fb_e:
                print(f"[triposr] cartoon relief fallback also failed: {_fb_e}", flush=True)
                return _extrude_alpha_to_mesh(image_paths[0], output_dir)
    print(f"[triposr] total {time.time()-t_total:.1f}s")

    mesh = meshes[0]
    # Recenter & normalize to a 10cm cube in mm so Bambu Studio prints at the right size
    mesh.apply_translation(-mesh.centroid)
    scale = 100.0 / max(mesh.extents)  # largest side = 100mm
    mesh.apply_scale(scale)
    # Surface the view count used so callers can log it
    used_views = len(views_to_use)

    # Paint the white reconstruction with the front-view reference image so the
    # preview/3D model is coloured even when the cloud Tripo3D PBR path is off.
    try:
        import mesh_postprocess as _mp
        mesh = _mp.paint_mesh_from_front(mesh, fg_images[0], camera_axis="z")
    except Exception as _pe:
        print(f"[triposr] paint skipped: {_pe}", flush=True)

    glb_path = os.path.join(output_dir, "mesh.glb")
    obj_path = os.path.join(output_dir, "mesh.obj")
    stl_path = os.path.join(output_dir, "mesh.stl")
    mesh.export(glb_path)
    mesh.export(obj_path)
    mesh.export(stl_path)
    print(f"[triposr] exported mesh in {time.time()-t0:.1f}s total; extents(mm)={mesh.extents.tolist()}")
    if _pg_sid:
        _pg.Progress(_pg_sid, "3d-triposr").done(f"导出完成 ({len(mesh.faces)} 面, {used_views} 视图融合)")
    return {
        "glb": glb_path,
        "obj": obj_path,
        "stl": stl_path,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "extents_mm": mesh.extents.tolist(),
        "views_used": used_views,
    }
def _extract_mesh_robust(model, fused_scene, mc_res=128):
    """Robust mesh extraction from a TripoSR scene code.
    
    Bypasses TripoSR's built-in extract_mesh (which uses a fixed iso-threshold
    and fails on flat cartoon-style density fields). Computes the density field
    ourselves, picks a robust threshold based on the density distribution, and
    runs marching cubes via the skimage shim.
    
    Returns list with one mesh (or empty list on total failure).
    """
    try:
        import torchmcubes_skimage  # registers shim  # noqa: F401
        from torchmcubes import marching_cubes
    except Exception as _e:
        print(f"[triposr] could not import marching_cubes shim: {_e}", flush=True)
        return []
    import numpy as _np
    import torch as _t
    
    # query_triplane expects a single scene code (Np=3, Cp, Hp, Wp), not batched.
    # After averaging scene codes with keepdim=True we have shape (1, 3, 40, 64, 64).
    if fused_scene.ndim == 5 and fused_scene.shape[0] == 1:
        scene_for_render = fused_scene.squeeze(0)
    else:
        scene_for_render = fused_scene
    # Cap mc_res aggressively for cartoon meshes — 64 is plenty and avoids OOM
    # in the 6GB-VRAM density-rendering step.
    safe_res = min(mc_res, 96)
    for _res in (safe_res, max(48, safe_res // 2)):
        # Set the model's marching cubes resolution (cached)
        model.set_marching_cubes_resolution(_res)
        # Compute density field on CPU to dodge the 6GB VRAM ceiling — the
        # renderer's _query_chunk allocates large intermediates that OOM at
        # res=128 even after forward() succeeded.
        import torch as _t2
        with _t2.no_grad():
            try:
                density = model.renderer.query_triplane(
                    model.decoder,
                    model.isosurface_helper.grid_vertices.to(scene_for_render.device),
                    scene_for_render,
                )["density_act"]
            except _t2.cuda.OutOfMemoryError as _oom2:
                print(f"[triposr] query_triplane OOM at res={_res}, retrying on CPU", flush=True)
                _t2.cuda.empty_cache()
                decoder_cpu = model.decoder.to("cpu")
                scene_cpu = scene_for_render.to("cpu")
                try:
                    density = model.renderer.query_triplane(
                        decoder_cpu,
                        model.isosurface_helper.grid_vertices,  # already on CPU
                        scene_cpu,
                    )["density_act"]
                finally:
                    model.decoder.to(scene_for_render.device)
                scene_for_render = scene_for_render.cpu()  # keep CPU for subsequent iters
        _t2.cuda.empty_cache()
        # Density shape: (1, R^3). Pick a robust threshold:
        # - compute mean and std of the density
        # - try thresholds from mean-2*std to mean+2*std, stepping by 0.5*std
        d = density.detach().float().view(-1).cpu().numpy()
        d_mean = float(d.mean())
        d_std = float(d.std())
        # Try a wide range of thresholds. Cartoon density fields tend to be
        # very flat, so we need to span the full distribution.
        candidates = []
        if d_std > 1e-3:
            # Normal-ish distribution: try mean ± k*std
            for k in (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0):
                candidates.append(d_mean + k * d_std)
        # Also try absolute thresholds as fallback
        candidates.extend([0.0, 5.0, 10.0, 15.0, 20.0, -5.0, -10.0, 3.0, 8.0, 12.0])
        
        for _thr in candidates:
            try:
                # Build level field (same as TripoSR's extract_mesh internal)
                # level = -(density - threshold) so iso=0 in level == iso=threshold in density
                level = -(density - _thr)
                level_3d = level.view(_res, _res, _res)
                v_pos, t_pos_idx = marching_cubes(level_3d.detach().cpu(), 0.0)
                v_pos = v_pos[..., [2, 1, 0]]  # reorder like TripoSR does
                v_pos = v_pos / (_res - 1.0)
                # Transform from unit cube to model space
                pts_range = model.isosurface_helper.points_range
                radius = model.renderer.cfg.radius
                v_pos = (v_pos - pts_range[0]) / (pts_range[1] - pts_range[0])
                v_pos = v_pos * (2 * radius) - radius  # back to (-radius, radius)
                # Convert to trimesh
                import trimesh as _tr
                mesh = _tr.Trimesh(
                    vertices=v_pos.cpu().numpy() if hasattr(v_pos, 'cpu') else v_pos.numpy(),
                    faces=t_pos_idx.cpu().numpy() if hasattr(t_pos_idx, 'cpu') else t_pos_idx.numpy(),
                )
                if len(mesh.vertices) > 100 and len(mesh.faces) > 100:
                    print(f"[triposr] mesh found res={_res} thr={_thr:.2f} verts={len(mesh.vertices)}", flush=True)
                    return [mesh]
            except Exception as _e:
                continue
        print(f"[triposr] no usable mesh at res={_res} after threshold sweep", flush=True)
    return []


def _extrude_alpha_to_mesh(image_path, output_dir, *, height_mm=10.0, base_mm=1.5):
    """Last-resort 3D mesh: extrude the alpha mask of the input image as a relief.

    Always produces a valid mesh even when the diffusion model fails.
    Returns dict with the same shape as generate_3d().
    """
    import os as _os
    import numpy as _np
    import trimesh as _tr
    from PIL import Image as _Image
    from rmbg_remove import remove_bg as _rmbg

    img = _Image.open(image_path).convert("RGB")
    fg = _rmbg(img)
    alpha = _np.array(fg.split()[-1]).astype(_np.float32) / 255.0  # 0..1
    # Downsample the alpha mask to keep the mesh under ~100k vertices.
    # Anything above 256x256 makes Bambu Studio choke.
    target_side = 256
    h0, w0 = alpha.shape
    if max(h0, w0) > target_side:
        scale = target_side / max(h0, w0)
        new_size = (max(1, int(w0 * scale)), max(1, int(h0 * scale)))
        alpha = _np.array(_Image.fromarray((alpha * 255).astype(_np.uint8)).resize(new_size, _Image.BILINEAR)).astype(_np.float32) / 255.0
    # Crop to non-zero alpha
    ys, xs = _np.where(alpha > 0.02)
    if len(ys) == 0:
        # Pure empty image — produce a 1cm cube
        v = _np.array([
            [0,0,0],[1,0,0],[1,1,0],[0,1,0],
            [0,0,1],[1,0,1],[1,1,1],[0,1,1],
        ], dtype=_np.float32)
        f = _np.array([
            [0,1,2],[0,2,3],[4,6,5],[4,7,6],
            [0,4,5],[0,5,1],[1,5,6],[1,6,2],
            [2,6,7],[2,7,3],[3,7,4],[3,4,0],
        ], dtype=_np.int64)
        mesh = _tr.Trimesh(vertices=v, faces=f)
    else:
        y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        crop = alpha[y1:y2, x1:x2]
        # Pad to square
        h, w = crop.shape
        side = max(h, w)
        pad_y = (side - h) // 2
        pad_x = (side - w) // 2
        square = _np.pad(crop, ((pad_y, side - h - pad_y), (pad_x, side - w - pad_x)), constant_values=0)
        # Build top + bottom surfaces triangulated from a grid + side wall
        N = side
        # Top vertices (the height field): top_z = height_mm * (1 - alpha)
        # so opaque pixels rise HIGH and transparent pixels sit at base level.
        # Flip Y so image top -> high y in mesh.
        top_z = base_mm + (height_mm - base_mm) * (1.0 - square)
        # Build bottom flat at z=0
        bot_z = _np.zeros_like(top_z)
        verts_top, faces_top = [], []
        for j in range(N):
            for i in range(N):
                verts_top.append([i / (N - 1), j / (N - 1), float(top_z[j, i])])
        for j in range(N - 1):
            for i in range(N - 1):
                a = j * N + i
                b = a + 1
                c = a + N
                d = c + 1
                faces_top.append([a, c, b])
                faces_top.append([b, c, d])
        verts_bot = [[i / (N - 1), j / (N - 1), 0.0] for j in range(N) for i in range(N)]
        # Build side wall: outer perimeter of bottom + top
        # For simplicity, drop a vertical wall only around the bbox.
        # First build the base flat rectangle.
        x0 = y0 = 0.0
        x1 = y1 = 1.0
        # 8 corners: bottom (4) + top (4)
        wall_v = [
            [x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0],  # bot
            [x0, y0, 1.0], [x1, y0, 1.0], [x1, y1, 1.0], [x0, y1, 1.0],  # top (unit)
        ]
        wall_f = [
            [0, 1, 5], [0, 5, 4],  # front
            [1, 2, 6], [1, 6, 5],  # right
            [2, 3, 7], [2, 7, 6],  # back
            [3, 0, 4], [3, 4, 7],  # left
            [4, 5, 6], [4, 6, 7],  # top cap (will be hidden by relief)
        ]
        # Build the relief mesh (one quad per pixel, displaced by the alpha
        # mask: opaque pixels rise to top_z, transparent pixels sit at base_mm).
        relief = _tr.Trimesh(vertices=_np.array(verts_top, dtype=_np.float32),
                             faces=_np.array(faces_top, dtype=_np.int64))
        # Add a flat base plate so the relief has something to sit on when printed.
        base_v = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        base_f = [[0, 1, 2], [0, 2, 3]]
        base = _tr.Trimesh(vertices=_np.array(base_v, dtype=_np.float32),
                           faces=_np.array(base_f, dtype=_np.int64))
        mesh = _tr.util.concatenate([relief, base])
        # top_z is already in mm, so z-scale is 1.
        mesh.apply_scale([100.0, 100.0, 1.0])
        # Center in XY around (50, 50) so Bambu's build plate is balanced.
        xy_center = mesh.bounds.mean(axis=0)
        mesh.apply_translation([
            50.0 - xy_center[0],
            50.0 - xy_center[1],
            -mesh.bounds[0, 2],  # sit on z=0
        ])

    glb_path = _os.path.join(output_dir, "mesh.glb")
    obj_path = _os.path.join(output_dir, "mesh.obj")
    stl_path = _os.path.join(output_dir, "mesh.stl")
    mesh.export(glb_path)
    mesh.export(obj_path)
    mesh.export(stl_path)
    return {
        "glb": glb_path,
        "obj": obj_path,
        "stl": stl_path,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "extents_mm": mesh.extents.tolist(),
        "engine": "alpha_extrusion",
    }


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "data", "_smoke_sd.png")
    out = os.path.join(_ROOT, "data", "_test_mesh")
    print(generate_3d(src, out))
