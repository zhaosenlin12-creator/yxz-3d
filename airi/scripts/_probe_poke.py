"""Which part of the face comes through the plate?

The plate is a polar grid around the mouth.  Its own height is
rasterised onto an XY map, and every vertex of the face around the
mouth is tested against it: a vertex that is further forward than the
plate at its own XY is a vertex that pokes out.
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "scripts")
from patch_yxz_mouth_surface import Asset, Face, grid_indices

path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/yxz-variants/r143-mouth/yxz.vrm")
a = Asset(path); d = a.document
bi = next(i for i, m in enumerate(d["meshes"]) if str(m.get("name", "")).startswith("tripo_mesh"))
face = Face(a, bi)
mi = next(i for i, m in enumerate(d["meshes"]) if m.get("name") == "YXZ_Mouth")
pr = d["meshes"][mi]["primitives"][0]
P = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
RINGS, SEGMENTS = 28, 144
FLAT = P.reshape(-1, 3)
idx = grid_indices(RINGS, SEGMENTS).reshape(-1, 3)
P1 = FLAT[idx[:, 0]]; P2 = FLAT[idx[:, 1]]; P3 = FLAT[idx[:, 2]]

centre = np.array([0.0, 0.0621, 0.2501])
cand = face.near(centre, 0.09)
tri = face.triangles[cand]
verts = face.positions[np.unique(tri)]

res = 0.00015
xs = np.arange(FLAT[:, 0].min() - res, FLAT[:, 0].max() + res, res)
ys = np.arange(FLAT[:, 1].min() - res, FLAT[:, 1].max() + res, res)
Z = np.full((len(xs), len(ys)), np.nan)
xi = np.arange(len(xs)); yi = np.arange(len(ys))

for k in range(len(idx)):
    a1, b1, c1 = P1[k], P2[k], P3[k]
    den = (b1[1] - c1[1]) * (a1[0] - c1[0]) + (c1[0] - b1[0]) * (a1[1] - c1[1])
    if abs(den) < 1e-18:
        continue
    i0 = max(0, int(np.floor(min(a1[0], b1[0], c1[0]) - xs[0]) / res))
    i1 = min(len(xs) - 1, int(np.ceil(max(a1[0], b1[0], c1[0]) - xs[0]) / res))
    j0 = max(0, int(np.floor(min(a1[1], b1[1], c1[1]) - ys[0]) / res))
    j1 = min(len(ys) - 1, int(np.ceil(max(a1[1], b1[1], c1[1]) - ys[0]) / res))
    if i1 < i0 or j1 < j0:
        continue
    X = xs[i0:i1 + 1][:, None]; Y = ys[j0:j1 + 1][None, :]
    l1 = ((b1[1] - c1[1]) * (X - c1[0]) + (c1[0] - b1[0]) * (Y - c1[1])) / den
    l2 = ((c1[1] - a1[1]) * (X - c1[0]) + (a1[0] - c1[0]) * (Y - c1[1])) / den
    l3 = 1.0 - l1 - l2
    inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
    if not inside.any():
        continue
    z = l1 * a1[2] + l2 * b1[2] + l3 * c1[2]
    sub = Z[i0:i1 + 1, j0:j1 + 1]
    better = inside & (np.isnan(sub) | (z > sub))
    Z[i0:i1 + 1, j0:j1 + 1] = np.where(better, z, sub)

col = np.clip(np.searchsorted(xs, verts[:, 0]) - 1, 0, len(xs) - 2)
row = np.clip(np.searchsorted(ys, verts[:, 1]) - 1, 0, len(ys) - 2)
z00 = Z[col, row]; z10 = Z[col + 1, row]; z01 = Z[col, row + 1]; z11 = Z[col + 1, row + 1]
fx = (verts[:, 0] - xs[col]) / res; fy = (verts[:, 1] - ys[row]) / res
pz = (z00 * (1 - fx) * (1 - fy) + z10 * fx * (1 - fy) + z01 * (1 - fx) * fy + z11 * fx * fy)
pz = np.where(np.isfinite(pz), pz, np.nan)
over = verts[:, 2] - pz
bad = np.isfinite(over) & (over > 0.00002)
print("face verts tested %d  outside plate footprint %d" % (len(verts), int((~np.isfinite(pz)).sum())))
print("verts poking through: %d" % int(bad.sum()))
if bad.sum():
    bv = verts[bad]; bo = over[bad]
    print("  max poke %.3f mm" % (bo.max() * 1000))
    for lo, hi in [(0.00002, 0.0005), (0.0005, 0.002), (0.002, 0.005), (0.005, 1.0)]:
        sel = (bo >= lo) & (bo < hi)
        if sel.sum() == 0: continue
        print("  poke %.2f-%.2f mm : %d verts  x %+.4f..%+.4f  y %+.4f..%+.4f" % (
            lo * 1000, hi * 1000, int(sel.sum()),
            bv[sel, 0].min(), bv[sel, 0].max(), bv[sel, 1].min(), bv[sel, 1].max()))
    vals, cnt = np.unique(np.round(bv[:, 1], 3), return_counts=True)
    order = np.argsort(-cnt)[:12]
    print("  y histogram:", [(float(vals[i]), int(cnt[i])) for i in order])
    print("  z range of poking verts: %.4f .. %.4f" % (bv[:, 2].min(), bv[:, 2].max()))
    vals, cnt = np.unique(np.round(bv[:, 2], 4), return_counts=True)
    order = np.argsort(-cnt)[:12]
    print("  z histogram:", [(float(vals[i]), int(cnt[i])) for i in order])
