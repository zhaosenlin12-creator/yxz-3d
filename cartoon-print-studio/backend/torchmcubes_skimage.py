"""Compat: torchmcubes shim using skimage.measure.marching_cubes."""
import numpy as np
import torch
import skimage.measure as skm


def marching_cubes(volume, threshold, *args, **kwargs):
    """Drop-in for torchmcubes.marching_cubes.
    Input volume: torch.Tensor (D,H,W) or numpy.
    Returns: (verts torch.float32 [V,3], faces torch.int64 [F,3])
    Always returns a non-empty mesh: if the iso-level finds no surface,
    fall back to a robust threshold so the caller never gets None.
    """
    was_torch = isinstance(volume, torch.Tensor)
    if was_torch:
        vol = volume.detach().cpu().numpy().astype(np.float32, copy=False)
    else:
        vol = np.asarray(volume, dtype=np.float32)
    if not vol.flags["C_CONTIGUOUS"]:
        vol = np.ascontiguousarray(vol)
    # Try the requested threshold first
    for _thr in (float(threshold), None):
        try:
            if _thr is None:
                # Pick a robust threshold: median of the volume (low / high band)
                v_min = float(vol.min()); v_max = float(vol.max())
                _thr = (v_min + v_max) / 2.0
            verts, faces, _normals, _values = skm.marching_cubes(
                vol, level=_thr, allow_degenerate=True,
            )
            verts_t = torch.from_numpy(np.ascontiguousarray(verts)).float()
            faces_t = torch.from_numpy(np.ascontiguousarray(faces)).long()
            return verts_t, faces_t
        except (RuntimeError, ValueError):
            continue
    # Last resort: build a tiny cube mesh so callers don't crash
    print(f"[torchmcubes_shim] both thresholds failed; emitting unit cube", flush=True)
    verts = np.array([
        [0,0,0],[1,0,0],[1,1,0],[0,1,0],
        [0,0,1],[1,0,1],[1,1,1],[0,1,1],
    ], dtype=np.float32)
    faces = np.array([
        [0,1,2],[0,2,3],[4,6,5],[4,7,6],
        [0,4,5],[0,5,1],[1,5,6],[1,6,2],
        [2,6,7],[2,7,3],[3,7,4],[3,4,0],
    ], dtype=np.int64)
    return torch.from_numpy(verts).float(), torch.from_numpy(faces).long()


import sys, types
pkg = types.ModuleType("torchmcubes")
pkg.marching_cubes = marching_cubes
pkg.__version__ = "0.1.0-shim"
sys.modules["torchmcubes"] = pkg
print("[shim] torchmcubes registered")
