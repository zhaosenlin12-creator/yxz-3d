import re
from pathlib import Path
p = Path("scripts/finish_yxz_mouth.py")
text = p.read_text(encoding="utf-8")

old_start = text.index("    # --- the inside of the mouth ---------------------------------------")
old_end = text.index("    shade = np.clip((field[painted] - 0.15) / 0.85, 0.0, 1.0)[:, None]")

new = '''    # --- the inside of the mouth ---------------------------------------
    # The paint is put on the face the way the face is actually painted:
    # a dense grid of points around the mouth is put on the surface, and
    # the texture coordinate there is the one the face carries.
    step = 0.0004
    grid_x = np.arange(CENTRE[0] - 0.048, CENTRE[0] + 0.048, step)
    grid_y = np.arange(CENTRE[1] - 0.034, CENTRE[1] + 0.034, step)
    mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
    probes = np.column_stack([
        mesh_x.reshape(-1), mesh_y.reshape(-1),
        np.full(mesh_x.size, 0.2501)])
    offsets = probes[:, :2] - CENTRE
    covered = inside_any(offsets)
    probes = probes[covered]
    values = depth_in_mouth(offsets)[covered]
    print("YXZ_FINISH %d probes inside the mouth" % len(probes))

    xs, ys, depth_map, hit = heightmap(
        face, np.array([CENTRE[0], CENTRE[1], 0.2501]),
        0.058, 0.044, 0.0002, candidates)
    _, _, uvs_on_face = sample_surface(
        face, xs, ys, hit, probes[:, 0], probes[:, 1])
    face_x = uvs_on_face[:, 0] * width_px
    face_y = uvs_on_face[:, 1] * height_px
    face_ix = np.clip(np.round(face_x).astype(int), 0, width_px - 1)
    face_iy = np.clip(np.round(face_y).astype(int), 0, height_px - 1)

    field = np.full((height_px, width_px), np.nan)
    np.fmin.at(field, (face_iy, face_ix), values)
    field = spread(field, 8)

    painted = np.isfinite(field)
    ys_painted, xs_painted = np.nonzero(painted)
    print("YXZ_FINISH painted %d pixels, x %d..%d y %d..%d"
          % (len(ys_painted), xs_painted.min(), xs_painted.max(),
             ys_painted.min(), ys_painted.max()))

'''
text = text[:old_start] + new + text[old_end:]
text = text.replace(
    "from rebuild_yxz_mouth import SHAPES  # noqa: E402",
    "from rebuild_yxz_mouth import (  # noqa: E402\n    SHAPES, heightmap, sample_surface)")
p.write_text(text, encoding="utf-8")
print("patched")
