"""Does the face come through the plate?

For every triangle of the plate, the point at its middle is looked at
from straight in front: the frontmost piece of the face under that
point is found by testing the face's triangles, and the plate is in
front when its own surface is further forward than that.
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face

path = Path(sys.argv[1] if len(sys.argv)>1 else "docs/yxz-variants/r143-mouth/yxz.vrm")
a=Asset(path); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
I=a.accessor(pr["indices"]).reshape(-1,3)

centre=np.array([0.0,0.0621,0.2501])
cand=face.near(centre,0.09)
tri=face.triangles[cand]
A=face.positions[tri[:,0]]; B=face.positions[tri[:,1]]; C=face.positions[tri[:,2]]
AB=B-A; AC=C-A
d00=AB[:,0]*AB[:,0]+AB[:,1]*AB[:,1]
d01=AB[:,0]*AC[:,0]+AB[:,1]*AC[:,1]
d11=AC[:,0]*AC[:,0]+AC[:,1]*AC[:,1]
denom=d00*d11-d01*d01
ok=np.abs(denom)>1e-22

mid=P[I].mean(axis=1)
front=np.full(len(mid),-np.inf)
CH=800
for start in range(0,len(mid),CH):
    pts=mid[start:start+CH]
    p20=pts[:,None,0]-A[None,:,0]; p21=pts[:,None,1]-A[None,:,1]
    with np.errstate(all="ignore"):
        d20=p20*AB[None,:,0]+p21*AB[None,:,1]
        d21=p20*AC[None,:,0]+p21*AC[None,:,1]
        wb=(d11[None,:]*d20-d01[None,:]*d21)/denom[None,:]
        wc=(d00[None,:]*d21-d01[None,:]*d20)/denom[None,:]
    wa=1.0-wb-wc
    inside=(wa>=-1e-6)&(wb>=-1e-6)&(wc>=-1e-6)&ok[None,:]
    z=wa*A[None,:,2]+wb*B[None,:,2]+wc*C[None,:,2]
    z=np.where(inside,z,-np.inf)
    front[start:start+CH]=z.max(axis=1)

clear=mid[:,2]-front
miss=front==-np.inf
print("plate triangles %d   no face under them: %d"%(len(clear),int(miss.sum())))
valid=clear[~miss]
if len(valid):
    print("clearance mm: min %.3f  1%% %.3f  median %.3f"%(valid.min()*1000,np.percentile(valid,1)*1000,np.median(valid)*1000))
bad=np.nonzero((clear<0)&(~miss))[0]
print("triangles where the face is in front: %d (%.2f%%)"%(len(bad),100.0*len(bad)/len(clear)))
for k in bad[np.argsort(clear[bad])][:15]:
    print("   clearance %+.3f mm at x %+.4f y %+.4f  plate z %.4f  face z %.4f"%(clear[k]*1000,mid[k,0],mid[k,1],mid[k,2],front[k]))
if len(bad):
    ys=mid[bad][:,1]
    import collections
    hist=collections.Counter(np.round(ys,3).tolist())
    print("  worst rows:",sorted(hist.items(), key=lambda kv:-kv[1])[:10])
