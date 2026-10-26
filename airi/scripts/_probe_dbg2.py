import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
a=Asset(Path("docs/yxz-variants/r143-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
centre=np.array([0.0,0.0621,0.2501])
cand=face.near(centre,0.09)
tri=face.triangles[cand]
A=face.positions[tri[:,0]]; B=face.positions[tri[:,1]]; C=face.positions[tri[:,2]]
print("candidates",len(cand))
# pick a triangle whose centroid is near the mouth centre in XY and z
cen=(A+B+C)/3
m=(np.abs(cen[:,0])<0.005)&(np.abs(cen[:,1]-0.0621)<0.005)&(cen[:,2]>0.20)
print("triangles whose centroid is right at the mouth centre:",m.sum())
for k in np.nonzero(m)[0][:4]:
    print("  tri",cand[k],"centroid",cen[k].round(4))
k=np.nonzero(m)[0][0]
px,py=cen[k,0],cen[k,1]
AB=B-A; AC=C-A
d00=(AB*AB).sum(1); d01=(AB*AC).sum(1); d11=(AC*AC).sum(1)
denom=d00*d11-d01*d01
p20=px-A[:,0]; p21=py-A[:,1]
with np.errstate(all="ignore"):
    wb=(d11*p20-d01*p21)/denom; wc=(d00*p21-d01*p20)/denom
wa=1.0-wb-wc
print("weights for that triangle: %.6f %.6f %.6f  denom %.3e"%(wa[k],wb[k],wc[k],denom[k]))
print("denom percentiles:", np.percentile(denom,[0,1,5,50,100]))
