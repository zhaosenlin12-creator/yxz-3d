import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
a=Asset(Path("docs/yxz-variants/r143-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
print("face triangles",len(face.triangles))
corners=face.positions[face.triangles]
a3,b3,c3=corners[:,0],corners[:,1],corners[:,2]
ab=b3-a3; ac=c3-a3
d00=(ab*ab).sum(1); d01=(ab*ac).sum(1); d11=(ac*ac).sum(1)
denom=d00*d11-d01*d01
print("denom: min %.3e  median %.3e  max %.3e   zero-ish %d"%(denom.min(),np.median(denom),denom.max(),(denom<1e-18).sum()))
for pt in [(0.0,0.0621),(0.0,0.0500),(-0.0289,0.0634)]:
    px,py=pt
    p20=px-a3[:,0]; p21=py-a3[:,1]
    with np.errstate(all="ignore"):
        wb=(d11*p20-d01*p21)/denom; wc=(d00*p21-d01*p20)/denom; wa=1.0-wb-wc
    inside=(wa>=-1e-9)&(wb>=-1e-9)&(wc>=-1e-9)&np.isfinite(wa)&np.isfinite(wb)&np.isfinite(wc)
    print(pt,"covered by",inside.sum(),"triangles")
    if inside.any():
        z=wa[inside]*a3[inside,2]+wb[inside]*b3[inside,2]+wc[inside]*c3[inside,2]
        print("   z range %.4f .. %.4f"%(z.min(),z.max()))
