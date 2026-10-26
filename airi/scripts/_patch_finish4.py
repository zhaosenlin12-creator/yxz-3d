from pathlib import Path
p = Path("scripts/finish_yxz_mouth.py")
t = p.read_text(encoding="utf-8")
old = """        angle = np.mod(np.arctan2(y - centre[1], x - centre[0]), 2.0 * np.pi)
        rim = np.interp(angle, np.linspace(0.0, 2.0 * np.pi,
                                          LINING_PLATE_SEGMENTS + 1),
                        np.concatenate([grid[0], grid[0][:1]])[:, 2])
        return np.where(np.isfinite(found), found, rim), np.isfinite(found)"""
new = """        # The hole is a long thin ellipse, so a point inside it cannot
        # be placed on the rim by the angle it makes with the centre:
        # every point along the slit has the same angle as one end of
        # it.  The ellipse's own parameter is what puts a point on the
        # rim it belongs to.
        half_width = max(abs(grid[0][:, 0] - centre[0]).max(), 1e-6)
        half_height = max(abs(grid[0][:, 1] - centre[1]).max(), 1e-6)
        angle = np.mod(np.arctan2((y - centre[1]) / half_height,
                                  (x - centre[0]) / half_width), 2.0 * np.pi)
        rim = np.interp(angle, np.linspace(0.0, 2.0 * np.pi,
                                          LINING_PLATE_SEGMENTS + 1),
                        np.concatenate([grid[0], grid[0][:1]])[:, 2])
        return np.where(np.isfinite(found), found, rim), np.isfinite(found)"""
assert old in t
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("patched")
