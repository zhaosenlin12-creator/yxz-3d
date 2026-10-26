import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face, closest_on_triangle, barycentric

a=Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
U=a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
centre=P[:144].mean(axis=0)
cand=face.near(centre, 0.12)
# nearest face vertex (true surface) for each plate vertex
pool=np.unique(face.triangles[cand].reshape(-1))
sp=face.positions[pool]
best=np.full(len(P), np.inf); hit=np.zeros(len(P),dtype=int)
for s in range(0,len(sp),20000):
    ch=sp[s:s+20000]
    dist=np.linalg.norm(P[:,None,:]-ch[None,:,:],axis=2)
    n=dist.argmin(axis=1); v=dist[np.arange(len(P)),n]
    c=v<best; best=np.where(c,v,best); hit=np.where(c,pool[s+n],hit)
fu=face.uvs[hit]; fn=face.normals[hit]; fp=face.positions[hit]
print("plate->nearest face vertex distance: max %.5f mean %.5f"%(best.max(),best.mean()))
front = fn[:,2]>0
print("nearest face vertex is front-facing: %.2f of vertices"%front.mean())
for name, sel in (("FRONT", front), ("BACK", ~front)):
    if sel.sum()==0: continue
    print(" %s: plate uv x %.0f..%.0f y %.0f..%.0f | face uv x %.0f..%.0f y %.0f..%.0f | face z %.4f..%.4f"%(
      name, U[sel,0].min()*4096, U[sel,0].max()*4096, (1-U[sel,1].min())*4096, (1-U[sel,1].max())*4096,
      fu[sel,0].min()*4096, fu[sel,0].max()*4096, (1-fu[sel,1].min())*4096,(1-fu[sel,1].max())*4096,
      fp[sel,2].min(), fp[sel,2].max()))
# how well do plate uvs match the face's own uv at the nearest vertex?
err = np.linalg.norm((U-fu)*np.array([4096,4096]), axis=1)
print("uv mismatch (px) between plate and face: mean %.1f max %.1f"%(err.mean(), err.max()))
print("plate ring index of mismatched:", np.nonzero(err>30)[0][:10], "count", (err>30).sum())
# face mesh density near the mouth
for r in (0.012,0.02,0.03,0.05):
    print("face verts within %dmm: %d"%(r*1000, (np.linalg.norm(face.positions-centre,axis=1)<r).sum()))
