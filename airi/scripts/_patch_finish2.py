import re
from pathlib import Path
p = Path("scripts/finish_yxz_mouth.py")
t = p.read_text(encoding="utf-8")

t = t.replace("""BOWL_WIDTH = 0.048
BOWL_HEIGHT = 0.021
BOWL_DEPTH = 0.0035
BOWL_FLAT = 0.45""", """BOWL_WIDTH = 0.048
BOWL_HEIGHT = 0.021
BOWL_DEPTH = 0.0100
BOWL_FLAT = 0.78""")

t = t.replace("""# The lining: a bowl inside the bowl, sitting just in front of the
# hollowed face so that it can never fight with it for the same pixels.
LINING_RADIUS = 0.80
LINING_RINGS = 12
LINING_SEGMENTS = 144
LINING_CLEARANCE = 0.0009""", """# The lining: a copy of the plate, three millimetres behind it, with
# the hole in the plate filled in.  It is built from the plate's own
# surface rather than from the face's, because the plate's surface is
# what the lining has to stay behind.
LINING_WIDTH = 0.034
LINING_HEIGHT = 0.017
LINING_RINGS = 14
LINING_SEGMENTS = 288
LINING_CLEARANCE = 0.0030""")

# replace build_lining with a version that follows the plate
start = t.index("def build_lining(face, surface, candidates):")
end = t.index("def main():")
new = '''def build_lining(face, plate, indices, centre):
    """The dark bowl that lines the hollowed muzzle.

    The lining is a copy of the plate, a few millimetres behind it and
    with the plate's own hole filled in.  It is built from the plate's
    surface because that is the surface it has to stay behind: the face
    turns over a steep edge at the lower lip, and there the plate cuts
    across the edge while the face does not.
    """
    ring = plate[:indices.shape[1]] if False else None
    segments = int(indices.max()) + 1
    # The plate's grid: the first ring is the rim of its hole.
    grid = plate.reshape(-1, LINING_PLATE_SEGMENTS)

    def plate_z(x, y, fallback):
        """The plate's own height at a point, and the hole rim's if it
        falls inside the hole."""
        a = plate[indices[:, 0]]
        b = plate[indices[:, 1]]
        c = plate[indices[:, 2]]
        ab = b - a
        ac = c - a
        d00 = ab[:, 0] * ab[:, 0] + ab[:, 1] * ab[:, 1]
        d01 = ab[:, 0] * ac[:, 0] + ab[:, 1] * ac[:, 1]
        d11 = ac[:, 0] * ac[:, 0] + ac[:, 1] * ac[:, 1]
        denom = d00 * d11 - d01 * d01
        usable = np.abs(denom) > 1e-22
        px = x[:, None]
        py = y[:, None]
        d20 = (px - a[None, :, 0]) * ab[None, :, 0] \\
            + (py - a[None, :, 1]) * ab[None, :, 1]
        d21 = (px - a[None, :, 0]) * ac[None, :, 0] \\
            + (py - a[None, :, 1]) * ac[None, :, 1]
        with np.errstate(all="ignore"):
            weight_b = (d11[None, :] * d20 - d01[None, :] * d21) / denom[None, :]
            weight_c = (d00[None, :] * d21 - d01[None, :] * d20) / denom[None, :]
        weight_a = 1.0 - weight_b - weight_c
        inside = (weight_a >= -1e-9) & (weight_b >= -1e-9) & (weight_c >= -1e-9) \\
            & usable[None, :]
        z = weight_a * a[None, :, 2] \\
            + weight_b * b[None, :, 2] \\
            + weight_c * c[None, :, 2]
        z = np.where(inside, z, -np.inf)
        best = z.argmax(axis=1)
        rows = np.arange(len(x))
        found = z[rows, best]
        angle = np.mod(np.arctan2(y - centre[1], x - centre[0]), 2.0 * np.pi)
        rim = np.interp(angle, np.linspace(0.0, 2.0 * np.pi,
                                          LINING_PLATE_SEGMENTS + 1),
                        np.concatenate([grid[0], grid[0][:1]])[:, 2])
        return np.where(np.isfinite(found), found, rim), np.isfinite(found)

    angle = np.linspace(0.0, 2.0 * np.pi, LINING_SEGMENTS, endpoint=False)
    rings = []
    for step in range(LINING_RINGS + 1):
        radius = 1.0 - step / LINING_RINGS
        x = centre[0] + LINING_WIDTH * radius * np.cos(angle)
        y = centre[1] + LINING_HEIGHT * radius * np.sin(angle)
        z, _ = plate_z(x, y, None)
        rings.append(np.column_stack([x, y, z - LINING_CLEARANCE]))
    points = np.concatenate(rings, axis=0)

    floor = np.array([[centre[0], centre[1],
                       rings[-1][:, 2].mean() - 0.0015]])
    points = np.concatenate([floor, points], axis=0)

    triangles = []
    for segment in range(LINING_SEGMENTS):
        following = (segment + 1) % LINING_SEGMENTS
        triangles.extend([0, 1 + segment, 1 + following])
    for ring_index in range(LINING_RINGS):
        lower = 1 + ring_index * LINING_SEGMENTS
        upper = lower + LINING_SEGMENTS
        for segment in range(LINING_SEGMENTS):
            following = (segment + 1) % LINING_SEGMENTS
            a = lower + segment
            b = lower + following
            c = upper + following
            d = upper + segment
            triangles.extend([a, c, b, a, d, c])
    return points, np.array(triangles, dtype=np.int64), points


'''
t = t[:start] + new + t[end:]

t = t.replace("""    lining, lining_triangles, lining_grid = build_lining(
        face, surface, candidates)""", """    lining, lining_triangles, lining_grid = build_lining(
        face, plate, indices, CENTRE)""")

t = t.replace("""LINING_CLEARANCE = 0.0030""", """LINING_CLEARANCE = 0.0030

# The plate's own grid: how many points around it and how many rings.
LINING_PLATE_RINGS = 28
LINING_PLATE_SEGMENTS = 144""")

p.write_text(t, encoding="utf-8")
print("patched")
