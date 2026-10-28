"""Mesh post-processing utilities for cartoon-print-studio."""
from __future__ import annotations
import os
from typing import Optional

import numpy as np
import trimesh

PRINT_HEIGHT_MM_DEFAULT = 12.0
PRINT_LENGTH_MM = 100.0
MAX_DEBRIS_DIAMETER_MM = 5.0


def paint_mesh_from_front(mesh, ref_image, *, camera_axis="z"):
    """Paint a white/grey reconstruction mesh with a front-view reference image.

    Planar projection: the camera sits on `camera_axis` (default +z), the image
    plane covers the other two axes. Vertex colours are attached so GLB/OBJ
    exports keep the cartoon paint; STL stays colourless (slicer format).

    Returns the same mesh with `visual` replaced. If the image has no alpha
    (or projection fails) the mesh is returned unchanged.
    """
    try:
        from PIL import Image as _PILImage
        rgb = np.asarray(_PILImage.fromarray(np.asarray(ref_image)).convert("RGB")).astype(np.float32) / 255.0
    except Exception as _e:
        print(f"[mesh] paint skip (image): {_e}", flush=True)
        return mesh
    if mesh is None or not len(mesh.vertices):
        return mesh
    try:
        H, W = rgb.shape[:2]
        if H < 4 or W < 4:
            return mesh
        v = mesh.vertices
        if camera_axis == "z":
            xs, ys = v[:, 0], v[:, 1]
        elif camera_axis == "y":
            xs, ys = v[:, 0], v[:, 2]
        elif camera_axis == "x":
            xs, ys = v[:, 1], v[:, 2]
        else:
            xs, ys = v[:, 0], v[:, 1]
        lo_x, hi_x = float(xs.min()), float(xs.max())
        lo_y, hi_y = float(ys.min()), float(ys.max())
        if (hi_x - lo_x) < 1e-9 or (hi_y - lo_y) < 1e-9:
            return mesh
        u = (xs - lo_x) / (hi_x - lo_x)
        vv = (ys - lo_y) / (hi_y - lo_y)
        px = np.clip((u * (W - 1)).astype(np.int64), 0, W - 1)
        py = np.clip(((1.0 - vv) * (H - 1)).astype(np.int64), 0, H - 1)
        colors = rgb[py, px]
        rgba = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
        rgba[:, 0] = (colors[:, 0] * 255).astype(np.uint8)
        rgba[:, 1] = (colors[:, 1] * 255).astype(np.uint8)
        rgba[:, 2] = (colors[:, 2] * 255).astype(np.uint8)
        rgba[:, 3] = 255
        mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=rgba)
        print(f"[mesh] painted {len(mesh.vertices)} vertices from front view ({camera_axis})", flush=True)
    except Exception as _e:
        print(f"[mesh] paint skip (projection): {_e}", flush=True)
    return mesh


def _sanitize_printable_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Make a generated mesh acceptable to a slicer.

    Two problems are repaired here:
    - collapsed triangles (repeated or collinear vertices) leave edges that
      are only referenced once, so the whole file stops being watertight;
    - bodies whose winding disagrees make the signed volume collapse, which
      is what the printability preflight reports as "模型体积无效".

    Vertex colours are preserved because the relief keeps its cartoon paint.
    """
    if mesh is None or not len(mesh.faces):
        return mesh
    try:
        keep = np.asarray(mesh.nondegenerate_faces(), dtype=bool)
        areas = np.asarray(mesh.area_faces, dtype=float)
        keep = keep & (areas > 1e-12)
        if not keep.all():
            mesh.update_faces(np.nonzero(keep)[0])
            mesh.remove_unreferenced_vertices()
    except Exception as exc:  # pragma: no cover - defensive, keeps colours
        print(f"[mesh] degenerate face cleanup skipped: {exc}", flush=True)
    try:
        mesh.fix_normals(multibody=True)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[mesh] normal repair skipped: {exc}", flush=True)
    return mesh


def _rotate_y_up_to_z_up(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Convert a Y-up source mesh to the Z-up convention used by slicers.

    Hunyuan3D emits its upright axis as Y. Our printable exports, Bambu
    Studio included, use Z as the vertical axis. Keeping this conversion at
    the mesh boundary prevents a flat print bed from appearing as a vertical
    backdrop in the WebGL viewer.
    """
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return mesh


def _is_legacy_y_up_base(part: trimesh.Trimesh) -> bool:
    """Recognise the old XY base plate produced before coordinate alignment."""
    if len(part.faces) > 24:
        return False
    x, y, z = (float(v) for v in part.extents)
    return z <= 1.5 and x >= 20.0 and y >= 20.0


def has_legacy_y_up_base(mesh: trimesh.Trimesh) -> bool:
    """Whether an older generated file needs a one-time orientation upgrade."""
    parts = _geometry_parts(mesh)
    base_found = any(_is_legacy_y_up_base(part) for part in parts)
    if not base_found:
        return False
    body = max((part for part in parts if not _is_legacy_y_up_base(part)),
               key=lambda part: len(part.faces), default=None)
    if body is None:
        return False
    # In the legacy file the character's Y extent is its upright dimension.
    # A corrected Z-up file has the opposite relationship (Z is tallest).
    return float(body.extents[1]) > float(body.extents[2]) * 1.2


def upgrade_legacy_y_up_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Remove an obsolete XY plate, orient Y-up geometry for print, add a new base."""
    parts = [part for part in _geometry_parts(mesh) if not _is_legacy_y_up_base(part)]
    if not parts:
        return mesh
    body = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
    return clean_for_print(body, source_up="y", add_base=True)


def _face_groups(mesh: trimesh.Trimesh):
    """Connected-component groups expressed as original face indices.

    trimesh's own ``split()`` rebuilds the visual material for every part it
    produces, and for a textured mesh that copies the whole texture atlas
    once per part. On a 500k-face cloud model with PBR maps that exhausts
    memory and takes the backend process down with it. Face-index groups let
    us select components while paying for at most one texture copy.
    """
    if mesh is None or len(mesh.faces) == 0:
        return []
    try:
        from trimesh.graph import connected_components
        groups = connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
    except Exception as _e:
        print(f"[mesh] component split failed, keeping single body: {_e}", flush=True)
        return [np.arange(len(mesh.faces), dtype=np.int64)]
    return [np.asarray(group, dtype=np.int64) for group in groups]


def _select_faces(mesh: trimesh.Trimesh, face_indices):
    """Rebuild the mesh from a face subset, keeping the texture (one copy)."""
    indices = np.asarray(face_indices, dtype=np.int64)
    if len(indices) == 0 or len(indices) == len(mesh.faces):
        return mesh
    try:
        return mesh.submesh([indices], append=True, repair=False)
    except Exception as _e:
        print(f"[mesh] face subset failed: {_e}", flush=True)
        return mesh


def _part_from_group(mesh: trimesh.Trimesh, group):
    """One connected component as a geometry-only mesh (no texture copy)."""
    faces = mesh.faces[np.asarray(group, dtype=np.int64)]
    used, inverse = np.unique(faces.ravel(), return_inverse=True)
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices[used], dtype=np.float64),
        faces=inverse.reshape(faces.shape).astype(np.int64),
        process=False,
    )


def _geometry_parts(mesh: trimesh.Trimesh):
    """Connected components as geometry-only meshes (no texture copies)."""
    return [_part_from_group(mesh, group) for group in _face_groups(mesh)]


def component_count(mesh: trimesh.Trimesh) -> int:
    """How many disconnected bodies the mesh has."""
    return len(_face_groups(mesh))


def export_view_glb(mesh: trimesh.Trimesh, path: str) -> None:
    """Export a viewer GLB with disconnected parts as separate scene nodes.

    STL/OBJ are still exported as one combined mesh for slicers. Keeping the
    GLB parts separate lets the web workbench animate an honest explode view
    instead of pretending a single triangle soup has internal components.
    """
    groups = _face_groups(mesh)
    if len(groups) <= 1:
        mesh.export(path)
        return
    scene = trimesh.Scene()
    for index, group in enumerate(groups):
        part = _select_faces(mesh, group)
        scene.add_geometry(part, node_name=f"part_{index + 1}", geom_name=f"part_{index + 1}")
    scene.export(path)


def _largest_component(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    groups = _face_groups(mesh)
    if len(groups) == 1:
        return mesh
    groups.sort(key=len, reverse=True)
    return _select_faces(mesh, groups[0])


def _drop_tiny_debris(mesh: trimesh.Trimesh, max_diam_mm: float = MAX_DEBRIS_DIAMETER_MM) -> trimesh.Trimesh:
    groups = _face_groups(mesh)
    if len(groups) <= 1:
        return mesh
    keep = []
    for group in groups:
        verts = mesh.vertices[np.unique(mesh.faces[group])]
        d = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
        if d >= max_diam_mm:
            keep.append(group)
    if not keep:
        return mesh
    if len(keep) == 1:
        return _select_faces(mesh, keep[0])
    return _select_faces(mesh, np.concatenate(keep))


def _add_base_plate(mesh: trimesh.Trimesh, base_z: float = 0.6) -> trimesh.Trimesh:
    x0, y0 = mesh.bounds[0, 0], mesh.bounds[0, 1]
    x1, y1 = mesh.bounds[1, 0], mesh.bounds[1, 1]
    z = mesh.bounds[0, 2]
    v = np.array([
        [x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z],
        [x0, y0, z + base_z], [x1, y0, z + base_z], [x1, y1, z + base_z], [x0, y1, z + base_z],
    ], dtype=np.float32)
    f = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=np.int64)
    plate = trimesh.Trimesh(vertices=v, faces=f)
    return trimesh.util.concatenate([mesh, plate])


def _seal_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Close small perforations and make sure the surface faces outwards.

    Cloud generators hand back a shell with a lot of tiny holes. An open
    shell computes a meaningless volume (often negative, because the normals
    point inwards) and slicers then cut the model as if it were hollow.
    Filling the boundary loops and fixing the winding turns it back into a
    solid body.
    """
    try:
        from trimesh import repair
        if not mesh.is_watertight:
            repair.fill_holes(mesh, use_fan=True)
    except Exception as _e:
        print(f"[mesh] hole fill skipped: {_e}", flush=True)
    try:
        from trimesh import repair
        repair.fix_normals(mesh, multibody=True)
    except Exception as _e:
        print(f"[mesh] normal fix skipped: {_e}", flush=True)
    try:
        if mesh.volume < 0:
            mesh.invert()
    except Exception as _e:
        print(f"[mesh] inversion skipped: {_e}", flush=True)
    return mesh


def clean_for_print(mesh: trimesh.Trimesh, *,
                    add_base: bool = True,
                    max_side_mm: float = PRINT_LENGTH_MM,
                    drop_min_diam_mm: float = MAX_DEBRIS_DIAMETER_MM,
                    source_up: str = "z") -> trimesh.Trimesh:
    """Generic post-processing for AI-generated meshes.

    1. Align the source coordinate system to Z-up when needed.
    2. Re-scale so the largest side is max_side_mm (default 100mm).
    3. Drop tiny floating debris (the threshold is in millimetres, so this
       has to happen after the scaling).
    4. Keep only the largest connected component.
    5. Close small perforations and orient the surface outwards.
    6. Translate so the lowest point sits exactly on z=0.
    7. Optionally add a flat base plate matching the XY footprint.
    """
    if mesh is None or len(mesh.vertices) < 8:
        return mesh
    mesh = mesh.copy()
    if source_up.lower() == "y":
        mesh = _rotate_y_up_to_z_up(mesh)
    elif source_up.lower() != "z":
        raise ValueError("source_up must be 'y' or 'z'")
    # Scale before the debris filter: the threshold is expressed in
    # millimetres, and cloud models arrive in their own units (the Hunyuan
    # badge is ~0.65 units wide), so filtering first compared millimetres
    # against model units and kept or dropped the wrong geometry.
    ext = float(max(mesh.extents))
    if ext > 0:
        scale = max_side_mm / ext
        if 1e-4 < scale < 1e4:
            mesh.apply_scale(scale)
    mesh = _drop_tiny_debris(mesh, drop_min_diam_mm)
    mesh = _largest_component(mesh)
    if len(mesh.vertices) < 8:
        return mesh
    mesh = _seal_for_print(mesh)
    mesh.apply_translation([0, 0, -float(mesh.bounds[0, 2])])
    if add_base:
        mesh = _add_base_plate(mesh)
    return mesh


def _save_mesh(mesh: trimesh.Trimesh, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    glb = os.path.join(output_dir, "mesh.glb")
    obj = os.path.join(output_dir, "mesh.obj")
    stl = os.path.join(output_dir, "mesh.stl")
    mesh.export(glb)
    mesh.export(obj)
    mesh.export(stl)
    return {"glb": glb, "obj": obj, "stl": stl}


def _load_fg(image_path):
    """Load image and produce (rgb_white_bg, alpha) for silhouette extraction.

    Resolution order:
      1. Already-alpha image (RGBA, LA, or PA) -> use its alpha as-is.
      2. Flat RGB on white background -> threshold near-white pixels.
      3. Optional fallback to local rmbg (BriaRMBG) if installed AND torch is
         available. We never let a missing torch break this offline path,
         because the cartoon relief is supposed to work without any GPU.
    """
    from PIL import Image
    img = Image.open(image_path)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        rgba = np.array(img.convert("RGBA"))
        rgb = rgba[:, :, :3]
        alpha = rgba[:, :, 3].astype(np.float32) / 255.0
        white = np.full_like(rgb, 255)
        a = alpha[:, :, None]
        rgb = (rgb.astype(np.float32) * a + white.astype(np.float32) * (1 - a)).astype(np.uint8)
        return rgb, alpha

    rgb_arr = np.array(img.convert("RGB"))
    # Cheap white-background detection: anything within 12/255 of pure white
    # in all three channels is treated as background. This handles the case
    # where the upstream image generator returned an RGB-on-white PNG.
    diff = 255 - rgb_arr.min(axis=2)
    alpha = np.clip(diff.astype(np.float32) / 12.0, 0.0, 1.0)
    # Slight erosion so transparent halos at the silhouette edge are cleaned up.
    try:
        from scipy.ndimage import binary_erosion
        mask = alpha > 0.5
        eroded = binary_erosion(mask, iterations=1)
        alpha = np.where(eroded, alpha, 0.0).astype(np.float32)
    except Exception:
        pass
    return rgb_arr, alpha



def _load_alpha(image_path):
    _, alpha = _load_fg(image_path)
    return alpha


def _alpha_to_silhouette_mask(alpha: np.ndarray, target_side: int = 384) -> np.ndarray:
    h0, w0 = alpha.shape
    scale = target_side / max(h0, w0)
    new_size = (max(1, int(w0 * scale)), max(1, int(h0 * scale)))
    from PIL import Image
    img = Image.fromarray((alpha * 255).astype(np.uint8)).resize(new_size, Image.BILINEAR)
    arr = np.array(img).astype(np.float32) / 255.0
    h, w = arr.shape
    side = max(h, w)
    py = (side - h) // 2
    px = (side - w) // 2
    sq = np.zeros((side, side), dtype=np.float32)
    sq[py:py + h, px:px + w] = arr
    return sq


def _erode_alpha(alpha: np.ndarray, iterations: int = 1) -> np.ndarray:
    from scipy.ndimage import minimum_filter
    out = (alpha > 0.5).astype(np.float32)
    for _ in range(max(0, iterations)):
        out = minimum_filter(out, size=3)
    return out


def _build_layered_height_field(alpha: np.ndarray,
                                *,
                                layers: int = 5,
                                layer_step_mm: float = 1.6,
                                base_mm: float = 1.2,
                                depth_gamma: float = 1.2) -> np.ndarray:
    h, w = alpha.shape
    bin0 = (alpha > 0.5).astype(np.float32)
    if bin0.sum() == 0:
        return np.zeros_like(alpha)
    layer_idx = np.full_like(alpha, -1.0)
    current = bin0.copy()
    for li in range(layers):
        layer_idx[current > 0.5] = li
        current = _erode_alpha(current, iterations=max(1, int(layer_step_mm)))
        if current.sum() == 0:
            break
    if layer_idx.max() >= 0:
        from scipy.ndimage import distance_transform_edt
        dist = distance_transform_edt(bin0 > 0.5)
        max_d = max(1.0, float(dist.max()))
        norm = (dist / max_d) ** depth_gamma
        soft = alpha * (alpha > 0.05)
        soft_max = float(soft.max())
        soft_norm = soft / soft_max if soft_max > 0 else soft
        height = np.where(layer_idx >= 0,
                          base_mm + (layer_idx.astype(np.float32) * layer_step_mm) + norm * layer_step_mm * 0.4,
                          0.0)
        outer = (layer_idx == 0) & (alpha > 0)
        height = np.where(outer,
                          base_mm * 0.5 + base_mm * 0.5 * soft_norm,
                          height)
    else:
        height = np.zeros_like(alpha)
    return height.astype(np.float32)


def _height_field_to_mesh(height: np.ndarray, *,
                          xy_mm: float = PRINT_LENGTH_MM,
                          color_top: np.ndarray = None) -> trimesh.Trimesh:
    """Triangulate a height field as a watertight printable mesh that sits on z=0.

    If color_top[h,w,3] (uint8) is provided, top vertices get those colors so
    the resulting GLB can be viewed in color in a Three.js viewer. Side walls
    inherit a darker tint of the adjacent top color.
    """
    h, w = height.shape
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    top_x = (xx.astype(np.float32) / max(1, w - 1)) * xy_mm
    top_y = (yy.astype(np.float32) / max(1, h - 1)) * xy_mm
    top_z = height
    N = h * w
    verts_top = np.stack([top_x.ravel(), top_y.ravel(), top_z.ravel()], axis=1).astype(np.float32)
    verts_bot = np.stack([top_x.ravel(), top_y.ravel(), np.zeros(N, dtype=np.float32)], axis=1).astype(np.float32)
    if color_top is not None:
        ct = color_top.astype(np.float32) / 255.0
        if ct.ndim == 3:
            ct = ct.reshape(N, 3) if ct.shape[0] * ct.shape[1] == N else ct.reshape(-1, 3)
        colors_top = ct
    else:
        colors_top = np.full((N, 3), 0.7, dtype=np.float32)
    colors_bot = np.full((N, 3), 0.95, dtype=np.float32)
    colors_side_list = []
    verts_side_list = []
    top_faces = []
    for j in range(h - 1):
        for i in range(w - 1):
            a = j * w + i
            b = a + 1
            c = a + w
            d = c + 1
            if top_z[j, i] > 0 or top_z[j, i + 1] > 0 or top_z[j + 1, i] > 0:
                top_faces.append([a, b, c])
            if top_z[j, i + 1] > 0 or top_z[j + 1, i] > 0 or top_z[j + 1, i + 1] > 0:
                top_faces.append([b, d, c])
    top_faces = np.array(top_faces, dtype=np.int64) if top_faces else np.zeros((0, 3), dtype=np.int64)
    # Bottom faces (always full grid)
    bot_faces = []
    for j in range(h - 1):
        for i in range(w - 1):
            a = N + j * w + i
            b = a + 1
            c = a + w
            d = c + 1
            bot_faces.append([a, c, b])
            bot_faces.append([b, c, d])
    bot_faces = np.array(bot_faces, dtype=np.int64)
    # Side walls around the silhouette perimeter.
    side_faces = []
    for j in range(h):
        for i in range(w):
            if top_z[j, i] <= 0:
                continue
            for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nj, ni = j + dj, i + di
                if 0 <= nj < h and 0 <= ni < w and top_z[nj, ni] > 0:
                    continue
                x0 = (i / max(1, w - 1)) * xy_mm
                x1 = ((i + 1) / max(1, w - 1)) * xy_mm
                y0 = (j / max(1, h - 1)) * xy_mm
                y1 = ((j + 1) / max(1, h - 1)) * xy_mm
                z_t = float(top_z[j, i])
                if dj == -1:
                    pts = [(x0, y0, 0), (x1, y0, 0), (x1, y0, z_t), (x0, y0, z_t)]
                elif dj == 1:
                    pts = [(x1, y1, 0), (x0, y1, 0), (x0, y1, z_t), (x1, y1, z_t)]
                elif di == -1:
                    pts = [(x0, y1, 0), (x0, y0, 0), (x0, y0, z_t), (x0, y1, z_t)]
                else:
                    pts = [(x1, y0, 0), (x1, y1, 0), (x1, y1, z_t), (x1, y0, z_t)]
                base_idx = 2 * N + sum(len(v) for v in verts_side_list)
                verts_side_list.append(np.array(pts, dtype=np.float32))
                top_c = colors_top[j * w + i]
                side_c = (top_c * 0.7).clip(0, 1)
                colors_side_list.append(np.array([side_c] * 4, dtype=np.float32))
                side_faces.append([base_idx + 0, base_idx + 1, base_idx + 2])
                side_faces.append([base_idx + 0, base_idx + 2, base_idx + 3])
    # Cap the base perimeter so the bottom is closed.
    if (top_z > 0).any():
        base_idx = 2 * N + sum(len(v) for v in verts_side_list)
        verts_side_list.append(np.array([
            [0.0, 0.0, 0], [xy_mm, 0.0, 0], [xy_mm, xy_mm, 0], [0.0, xy_mm, 0],
        ], dtype=np.float32))
        if (top_z > 0).any():
            avg_top = colors_top[top_z.ravel() > 0].mean(axis=0)
        else:
            avg_top = colors_top.mean(axis=0)
        colors_side_list.append(np.array([avg_top * 0.6] * 4, dtype=np.float32))
        side_faces.append([base_idx + 0, base_idx + 2, base_idx + 1])
        side_faces.append([base_idx + 0, base_idx + 3, base_idx + 2])
    side_faces_arr = np.array(side_faces, dtype=np.int64) if side_faces else np.zeros((0, 3), dtype=np.int64)
    if verts_side_list:
        verts_side = np.vstack(verts_side_list)
        all_verts = np.vstack([verts_top, verts_bot, verts_side])
        all_colors = np.vstack([colors_top, colors_bot, np.vstack(colors_side_list)])
    else:
        all_verts = np.vstack([verts_top, verts_bot])
        all_colors = np.vstack([colors_top, colors_bot])
    all_faces = np.vstack([top_faces, bot_faces, side_faces_arr]) if len(side_faces_arr) > 0 else np.vstack([top_faces, bot_faces])
    mesh = trimesh.Trimesh(vertices=all_verts, faces=all_faces, vertex_colors=all_colors)
    return mesh
def cartoon_layered_relief(image_path: str, output_dir: str, *,
                           layers: int = 6,
                           layer_step_mm: float = 4.0,
                           base_mm: float = 2.0,
                           depth_gamma: float = 1.4,
                           xy_mm: float = PRINT_LENGTH_MM,
                           target_side: int = 384) -> dict:
    """Cartoon-optimized 3D path with the cartoon image baked as vertex colors.

    Result: a tall multi-layer relief (default ~26mm at 100mm base) that shows
    the actual cartoon character in color when viewed in a Three.js viewer.
    STL/OBJ exports drop the color (single-color 3D print friendly).
    """
    rgb, alpha = _load_fg(image_path)
    from PIL import Image as _PILImage
    h0, w0 = rgb.shape[:2]
    scale = target_side / max(h0, w0)
    new_size = (max(1, int(w0 * scale)), max(1, int(h0 * scale)))
    rgb_pil = _PILImage.fromarray(rgb).resize(new_size, _PILImage.BILINEAR)
    rgb_sq = np.array(rgb_pil)
    rh, rw = rgb_sq.shape[:2]
    side = max(rh, rw)
    py = (side - rh) // 2
    px = (side - rw) // 2
    rgb_canvas = np.full((side, side, 3), 255, dtype=np.uint8)
    rgb_canvas[py:py + rh, px:px + rw] = rgb_sq
    sq = _alpha_to_silhouette_mask(alpha, target_side=target_side)
    height = _build_layered_height_field(sq,
                                         layers=layers,
                                         layer_step_mm=layer_step_mm,
                                         base_mm=base_mm,
                                         depth_gamma=depth_gamma)
    mesh = _height_field_to_mesh(height, xy_mm=xy_mm, color_top=rgb_canvas)
    if max(mesh.extents) > 0:
        mesh.apply_translation([0, 0, -float(mesh.bounds[0, 2])])
    info = _save_mesh(mesh, output_dir)
    return {
        **info,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "extents_mm": mesh.extents.tolist(),
        "engine": "cartoon_relief_v2_colored",
        "layers": layers,
        "layer_step_mm": layer_step_mm,
        "base_mm": base_mm,
        "has_vertex_color": True,
    }
def _build_smooth_height_field(alpha, *, base_mm=1.0, max_depth_mm=14.0, depth_gamma=1.2):
    """Continuous height field (no staircase layers).

    The shape is a smooth dome:
    - outside silhouette: 0
    - at silhouette edge: ~base_mm (low)
    - at silhouette center: base_mm + max_depth_mm (high)
    """
    from scipy.ndimage import distance_transform_edt
    if (alpha > 0.05).sum() == 0:
        return np.zeros_like(alpha, dtype=np.float32)
    bin0 = (alpha > 0.05).astype(np.float32)
    dist = distance_transform_edt(bin0 > 0.5).astype(np.float32)
    max_d = max(1.0, float(dist.max()))
    norm = (dist / max_d).astype(np.float32) ** float(depth_gamma)
    height = np.where(
        alpha > 0.05,
        float(base_mm) + norm * float(max_depth_mm),
        0.0,
    ).astype(np.float32)
    return height


def cartoon_3d_figurine(image_path, output_dir, *,
                          base_mm=3.0,
                          depth_gamma=0.85,
                          max_depth_mm=22.0,
                          max_dim_mm=110.0,
                          thickness_mm=14.0,
                          back_thickness_mm=10.0,
                          back_scale=0.95,
                          target_side=768,
                          smooth_sigma=2.4,
                          dome_sigma=4.5,
                          base_disk_mm=2.5,
                          base_disk_scale=1.05,
                          edge_falloff_mm=4.0):
    """Round, thick cartoon figurine (v7).

    Geometry (Z up, Y is depth/thickness):
    - The cartoon image is the FRONT face, raised by (thickness + height_field).
    - The BACK face is a softer mirrored dome on the negative side — keeps the
      figurine volumetrically thick so it doesn't look like a keychain from the side.
    - The shape is *rounded*: heavy Gaussian smoothing kills eye/mouth pixel noise,
      and a distance-transform dome ensures the silhouette is plump instead of stepped.
    - A small round base disk sits under the figurine so it stands stable on the
      print bed without falling over.
    - Total Y extent (front+back) at center is roughly 2 * (thickness + max_depth),
      which gives a width:depth ratio close to 1.5:1 — looks "puffy" from any angle.
    """
    from PIL import Image as _PILImage
    rgb, alpha = _load_fg(image_path)

    mask = (alpha > 0.05)
    if mask.sum() == 0:
        mask = (alpha > 0.0)
    ys, xs = np.where(mask)
    if len(ys) == 0:
        info = _save_mesh(trimesh.Trimesh(), output_dir)
        return {**info, "vertices": 0, "faces": 0, "extents_mm": [0, 0, 0], "engine": "cartoon_figurine_v7_puffy"}
    y_lo, y_hi = int(ys.min()), int(ys.max()) + 1
    x_lo, x_hi = int(xs.min()), int(xs.max()) + 1
    rgb_trim = rgb[y_lo:y_hi, x_lo:x_hi]
    alpha_trim = alpha[y_lo:y_hi, x_lo:x_hi]

    th, tw = alpha_trim.shape
    scale = target_side / max(th, tw)
    new_h = max(1, int(round(th * scale)))
    new_w = max(1, int(round(tw * scale)))
    rgb_pil = _PILImage.fromarray(rgb_trim).resize((new_w, new_h), _PILImage.BILINEAR)
    alpha_pil = _PILImage.fromarray((alpha_trim * 255).astype(np.uint8)).resize((new_w, new_h), _PILImage.BILINEAR)
    rgb_canvas = np.array(rgb_pil)
    alpha_canvas = np.array(alpha_pil).astype(np.float32) / 255.0

    # --- v7 smoothing -----------------------------------------------
    # Two passes of blur:
    #   1. sigma=smooth_sigma removes pixel-level noise (cloth texture, eyes, mouth).
    #   2. A second broader blur only on the alpha creates the soft falloff
    #      used for the dome — keeps the silhouette plump instead of stepped.
    from scipy.ndimage import gaussian_filter as _gblur
    alpha_canvas = _gblur(alpha_canvas, sigma=float(smooth_sigma))
    rgb_canvas = _gblur(rgb_canvas.astype(np.float32), sigma=(float(smooth_sigma), float(smooth_sigma), 0)).clip(0, 255).astype(np.uint8)
    alpha_dome = _gblur(alpha_canvas, sigma=float(dome_sigma))

    # Smooth silhouette: pull the alpha boundary inward so we get a soft
    # skirt around the cartoon (printed figurine looks like a plushie, not a sticker).
    if edge_falloff_mm > 0:
        # Convert falloff in mm to pixels (relative to image scale)
        px_per_mm = target_side / float(max_dim_mm)
        falloff_px = float(edge_falloff_mm) * px_per_mm
        alpha_canvas = _gblur(alpha_canvas, sigma=falloff_px)

    width_mm = float(max_dim_mm) * (new_w / max(new_w, new_h))
    height_mm = float(max_dim_mm) * (new_h / max(new_w, new_h))

    # --- height field: rounded dome from the smoothed silhouette -------
    # Use the distance transform of the alpha; centre of the silhouette is the
    # highest point, edge is low. depth_gamma < 1 flattens the centre slightly
    # so the dome is round instead of conical.
    from scipy.ndimage import distance_transform_edt as _edt
    bin_alpha = (alpha_dome > 0.05).astype(np.float32)
    if bin_alpha.sum() == 0:
        bin_alpha = (alpha_canvas > 0.05).astype(np.float32)
    dist = _edt(bin_alpha > 0.5).astype(np.float32)
    max_d = max(1.0, float(dist.max()))
    norm = (dist / max_d).astype(np.float32) ** float(depth_gamma)
    height = np.where(
        alpha_canvas > 0.05,
        float(base_mm) + norm * float(max_depth_mm),
        0.0,
    ).astype(np.float32)
    # Extra smoothing on the height so the dome is buttery
    height = _gblur(height, sigma=1.0)

    h, w = height.shape
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    grid_x = ((xx.astype(np.float32) / max(1, w - 1)) - 0.5) * width_mm
    grid_z = (1.0 - yy.astype(np.float32) / max(1, h - 1)) * height_mm

    front_y_field = (float(thickness_mm) + height.astype(np.float32))
    back_y_field = (-float(back_thickness_mm) - height.astype(np.float32) * float(back_scale))

    N = h * w
    verts_front = np.stack([grid_x.ravel(), front_y_field.ravel(), grid_z.ravel()], axis=1).astype(np.float32)
    verts_back = np.stack([grid_x.ravel(), back_y_field.ravel(), grid_z.ravel()], axis=1).astype(np.float32)
    c_front = rgb_canvas.astype(np.float32).reshape(N, 3) / 255.0
    c_back = (rgb_canvas.astype(np.float32) * 0.62).reshape(N, 3) / 255.0  # back slightly brighter so print shows contrast

    # Front face — winding so outward normal faces +Y (toward camera).
    front_faces = []
    for j in range(h - 1):
        for i in range(w - 1):
            a = j * w + i
            b = a + 1
            c = a + w
            d = c + 1
            if height[j, i] > 0 or height[j, i + 1] > 0 or height[j + 1, i] > 0:
                front_faces.append([a, b, c])
            if height[j, i + 1] > 0 or height[j + 1, i] > 0 or height[j + 1, i + 1] > 0:
                front_faces.append([b, d, c])
    front_faces = np.array(front_faces, dtype=np.int64) if front_faces else np.zeros((0, 3), dtype=np.int64)

    # Back face — flipped winding so outward normal faces -Y.
    back_faces = []
    for j in range(h - 1):
        for i in range(w - 1):
            a = N + j * w + i
            b = a + 1
            c = a + w
            d = c + 1
            if height[j, i] > 0 or height[j, i + 1] > 0 or height[j + 1, i] > 0:
                back_faces.append([a, c, b])
            if height[j, i + 1] > 0 or height[j + 1, i] > 0 or height[j + 1, i + 1] > 0:
                back_faces.append([b, c, d])
    back_faces = np.array(back_faces, dtype=np.int64) if back_faces else np.zeros((0, 3), dtype=np.int64)

    # --- side walls along the silhouette perimeter ---------------------
    # For each pixel at the edge of the silhouette, build a quad that goes
    # from the back vertex to the front vertex along the y-axis. Reuse the
    # front-face and back-face vertex indices so the mesh stays watertight.
    side_verts_list = []
    side_colors_list = []
    side_faces = []
    # Index helpers: front[j*w+i] = j*w+i, back[j*w+i] = N + j*w+i
    def fidx(j, i): return j * w + i
    def bidx(j, i): return N + j * w + i
    for j in range(h):
        for i in range(w):
            if height[j, i] <= 0:
                continue
            for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nj, ni = j + dj, i + di
                in_bounds = 0 <= nj < h and 0 <= ni < w
                if in_bounds and height[nj, ni] > 0:
                    continue
                if dj == -1:
                    # top edge of cell (j, i): corners at (i, j) and (i+1, j)
                    i2 = min(i + 1, w - 1)
                    v_bb = bidx(j, i)
                    v_bc = bidx(j, i2)
                    v_ft = fidx(j, i2)
                    v_fl = fidx(j, i)
                    side_faces.append([v_bb, v_bc, v_ft])
                    side_faces.append([v_bb, v_ft, v_fl])
                elif dj == 1:
                    # bottom edge of cell (j, i): corners at (i, j+1) and (i+1, j+1)
                    i2 = min(i + 1, w - 1)
                    j2 = min(j + 1, h - 1)
                    v_bc = bidx(j2, i2)
                    v_bb = bidx(j2, i)
                    v_fl = fidx(j2, i)
                    v_fr = fidx(j2, i2)
                    side_faces.append([v_bc, v_bb, v_fl])
                    side_faces.append([v_bc, v_fl, v_fr])
                elif di == -1:
                    # left edge of cell (j, i): corners at (i, j) and (i, j+1)
                    j2 = min(j + 1, h - 1)
                    v_bb = bidx(j2, i)
                    v_bt = bidx(j, i)
                    v_ft = fidx(j, i)
                    v_fb = fidx(j2, i)
                    side_faces.append([v_bb, v_bt, v_ft])
                    side_faces.append([v_bb, v_ft, v_fb])
                else:
                    # right edge of cell (j, i): corners at (i+1, j) and (i+1, j+1)
                    i2 = min(i + 1, w - 1)
                    j2 = min(j + 1, h - 1)
                    v_bt = bidx(j, i2)
                    v_bb = bidx(j2, i2)
                    v_fb = fidx(j2, i2)
                    v_ft = fidx(j, i2)
                    side_faces.append([v_bt, v_bb, v_fb])
                    side_faces.append([v_bt, v_fb, v_ft])

    all_verts = np.vstack([verts_front, verts_back])
    all_colors = np.vstack([c_front, c_back])
    side_faces_arr = np.array(side_faces, dtype=np.int64) if side_faces else np.zeros((0, 3), dtype=np.int64)
    all_faces = np.vstack([front_faces, back_faces, side_faces_arr])

    # --- base disk --------------------------------------------------
    # A thin rounded disk under the figurine so it sits on the print bed
    # without the irregular silhouette edge touching z=0.
    if base_disk_mm > 0:
        cx = 0.0  # X centered
        cz = 0.0  # sits on the print bed (z=0)
        # Build an ellipse slightly larger than the figure footprint (X half-width and Z half-height).
        # base_disk_scale=1.05 means disk is just 5% wider than the figure.
        bbox_x = (width_mm / 2.0) * float(base_disk_scale)
        bbox_z = (height_mm / 2.0) * float(base_disk_scale)
        disk_n_x = 64
        disk_n_z = max(8, int(64 * bbox_z / max(bbox_x, 0.001)))
        disk_y_top = float(base_disk_mm)
        # Generate vertices along the ellipse perimeter + the disk interior as a single closed mesh
        # Use a tessellated cylinder with elliptical cross-section
        disk_verts = []
        disk_faces_d = []
        # top ring
        for k in range(disk_n_x):
            ang = 2.0 * np.pi * k / disk_n_x
            x = cx + bbox_x * np.cos(ang)
            z = cz + bbox_z * np.sin(ang)
            disk_verts.append([x, disk_y_top, z])
        # bottom ring
        for k in range(disk_n_x):
            ang = 2.0 * np.pi * k / disk_n_x
            x = cx + bbox_x * np.cos(ang)
            z = cz + bbox_z * np.sin(ang)
            disk_verts.append([x, 0.0, z])
        # side quads
        for k in range(disk_n_x):
            k2 = (k + 1) % disk_n_x
            top_a = k
            top_b = k2
            bot_a = k + disk_n_x
            bot_b = k2 + disk_n_x
            # Wind the wall outward so the disk closes as a solid body.
            disk_faces_d.append([bot_a, top_b, bot_b])
            disk_faces_d.append([bot_a, top_a, top_b])
        # bottom cap (single center fan)
        center_idx = len(disk_verts)
        disk_verts.append([cx, 0.0, cz])
        for k in range(disk_n_x):
            k2 = (k + 1) % disk_n_x
            disk_faces_d.append([center_idx, k + disk_n_x, k2 + disk_n_x])
        # top cap (single center fan) — sits at z=disk_y_top facing up
        top_center_idx = len(disk_verts)
        disk_verts.append([cx, disk_y_top, cz])
        for k in range(disk_n_x):
            k2 = (k + 1) % disk_n_x
            disk_faces_d.append([top_center_idx, k2, k])

        disk_verts = np.array(disk_verts, dtype=np.float32)
        disk_faces_d = np.array(disk_faces_d, dtype=np.int64)
        # Center the disk on the figure's centroid in X/Z
        fig_bb_min = all_verts.min(axis=0); fig_bb_max = all_verts.max(axis=0)  # just for centroid
        cx_target = 0.5 * (fig_bb_min[0] + fig_bb_max[0])
        cz_target = 0.5 * (fig_bb_min[2] + fig_bb_max[2])
        disk_verts[:, 0] += (cx_target - cx)
        disk_verts[:, 2] += (cz_target - cz)

        # Disk colors: averaged cartoon colour, slightly darker so it reads as base
        disk_center_color = (rgb_canvas.astype(np.float32).reshape(-1, 3).mean(axis=0) / 255.0) * 0.7
        disk_colors = np.tile(disk_center_color, (len(disk_verts), 1)).astype(np.float32)

        all_verts = np.vstack([all_verts, disk_verts])
        all_colors = np.vstack([all_colors, disk_colors])
        # offset disk face indices (side walls reuse front/back verts, no offset needed)
        disk_faces_d_offset = disk_faces_d + (2 * N)
        all_faces = np.vstack([all_faces, disk_faces_d_offset])

    mesh = trimesh.Trimesh(vertices=all_verts,
                          faces=all_faces,
                          vertex_colors=(all_colors * 255).astype(np.uint8))
    mesh = _sanitize_printable_mesh(mesh)

    # --- final placement -----------------------------------------------
    # Sit flat on z=0, center Y around 0, and lift slightly so the disk is the
    # only thing touching z=0.
    if len(mesh.vertices) > 0:
        bb = mesh.bounds
        mesh.apply_translation([0.0, 0.0, -float(bb[0, 2])])
        bb2 = mesh.bounds
        cy = 0.5 * (float(bb2[0, 1]) + float(bb2[1, 1]))
        mesh.apply_translation([0.0, -cy, 0.0])

    info = _save_mesh(mesh, output_dir)
    return {
        **info,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "extents_mm": mesh.extents.tolist(),
        "engine": "cartoon_figurine_v7_puffy_round",
        "base_mm": base_mm,
        "max_depth_mm": max_depth_mm,
        "thickness_mm": thickness_mm,
        "back_thickness_mm": back_thickness_mm,
        "back_scale": back_scale,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "has_vertex_color": True,
        "double_sided": True,
    }
