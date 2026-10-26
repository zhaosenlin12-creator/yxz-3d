import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
N=a.accessor(pr["attributes"]["NORMAL"]).astype(np.float64)
I=a.accessor(pr["indices"]).reshape(-1,3)
grazing = np.abs(N[:,2])<0.6
print("plate verts with |normal.z|<0.6:", grazing.sum(), "of", len(N))
if grazing.sum():
    print("  x %.4f..%.4f y %.4f..%.4f z %.4f..%.4f"%(P[grazing][:,0].min(),P[grazing][:,0].max(),P[grazing][:,1].min(),P[grazing][:,1].max(),P[grazing][:,2].min(),P[grazing][:,2].max()))
    print("  sample:", [(round(P[i][0],4),round(P[i][1],4),round(P[i][2],4),round(N[i][2],3)) for i in np.nonzero(grazing)[0][:8]])
# compare with the face's normals at the same points
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
pool=np.unique(face.triangles[face.near(P[:144].mean(axis=0),0.12)].reshape(-1))
sp=face.positions[pool]
best=np.full(len(P),np.inf); hit=np.zeros(len(P),dtype=int)
for s in range(0,len(sp),20000):
    ch=sp[s:s+20000]
    dist=np.linalg.norm(P[:,None,:]-ch[None,:,:],axis=2)
    n=dist.argmin(axis=1); v=dist[np.arange(len(P)),n]
    c=v<best; best=np.where(c,v,best); hit=np.where(c,pool[s+n],hit)
fn=face.normals[hit]
print("face normal |z| at the plate's grazing verts: min %.3f max %.3f mean %.3f"%(np.abs(fn[grazing][:,2]).min(),np.abs(fn[grazing][:,2]).max(),np.abs(fn[grazing][:,2]).mean()))
print("distance plate->nearest face vertex at those: mean %.5f"%best[grazing].mean())
