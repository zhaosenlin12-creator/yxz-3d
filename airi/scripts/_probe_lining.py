import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "scripts")
from patch_yxz_mouth_surface import Asset, Face

path = Path(sys.argv[1])
a = Asset(path); d = a.document
mi = next(i for i, m in enumerate(d["meshes"]) if m.get("name") == "YXZ_Mouth")
ci = next(i for i, m in enumerate(d["meshes"]) if m.get("name") == "YXZ_MouthCavity")
plate = a.accessor(d["meshes"][mi]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
idx = a.accessor(d["meshes"][mi]["primitives"][0]["indices"]).reshape(-1, 3).astype(np.int64)
lining = a.accessor(d["meshes"][ci]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
print("plate z %.4f .. %.4f   lining z %.4f .. %.4f" % (plate[:,2].min(), plate[:,2].max(), lining[:,2].min(), lining[:,2].max()))

# plate height at each lining vertex
A = plate[idx[:,0]]; B = plate[idx[:,1]]; C = plate[idx[:,2]]
ab = B - A; ac = C - A
d00 = ab[:,0]*ab[:,0]+ab[:,1]*ab[:,1]; d01 = ab[:,0]*ac[:,0]+ab[:,1]*ac[:,1]
d11 = ac[:,0]*ac[:,0]+ac[:,1]*ac[:,1]
den = d00*d11-d01*d01
ok = np.abs(den) > 1e-22
x = lining[:,0][:,None]; y = lining[:,1][:,None]
d20 = (x-A[None,:,0])*ab[None,:,0] + (y-A[None,:,1])*ab[None,:,1]
d21 = (x-A[None,:,0])*ac[None,:,0] + (y-A[None,:,1])*ac[None,:,1]
with np.errstate(all="ignore"):
    wb = (d11[None,:]*d20-d01[None,:]*d21)/den[None,:]
    wc = (d00[None,:]*d21-d01[None,:]*d20)/den[None,:]
wa = 1.0-wb-wc
inside = (wa>=-1e-9)&(wb>=-1e-9)&(wc>=-1e-9)&ok[None,:]
z = wa*A[None,:,2]+wb*B[None,:,2]+wc*C[None,:,2]
z = np.where(inside, z, -np.inf)
pz = z.max(axis=1)
front = np.isfinite(pz) & (lining[:,2] > pz)
print("lining verts in front of the plate: %d of %d" % (int(front.sum()), len(lining)))
if front.sum():
    v = lining[front]
    print("  x %+.4f..%+.4f  y %+.4f..%+.4f  z %.4f..%.4f" % (v[:,0].min(), v[:,0].max(), v[:,1].min(), v[:,1].max(), v[:,2].min(), v[:,2].max()))
    # how many are inside the plate hole (no plate triangle covers them)?
    print("  of those, uncovered by any plate triangle: %d" % int((~np.isfinite(pz[front])).sum()))
