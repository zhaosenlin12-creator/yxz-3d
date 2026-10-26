"""Does the face come through the plate?

The test is a real one: for every triangle of the plate, the point at
its middle is looked at from straight in front, and the frontmost piece
of the face that is under that point is found by testing every
triangle of the face that covers it.  The plate is in front when its
own surface is further forward than that.
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

corners=face.positions[face.triangles]
a3,b3,c3=corners[:,0],corners[:,1],corners[:,2]
ab=b3-a3; ac=c3-a3
d00=(ab*ab).sum(1); d01=(ab*ac).sum(1); d11=(ac*ac).sum(1)
denom=d00*d11-d01*d01
good=np.abs(denom)>1e-18
keep=np.nonzero(good)[0]

mid=P[I].mean(axis=1)
front=np.full(len(mid),-np.inf)
for row in range(len(mid)):
    px=mid[row,0]; py=mid[row,1]
    ax=a3[keep,0]; ay=a3[keep,1]
    p20=px-ax; p21=py-ay
    wb=(d11[keep]*p20-d01[keep]*p21)/denom[keep]
    wc=(d00[keep]*p21-d01[keep]*p20)/denom[keep]
    wa=1.0-wb-wc
    inside=(wa>=-1e-6)&(wb>=-1e-6)&(wc>=-1e-6)
    if inside.any():
        z=wa[inside]*a3[keep][inside,2]+wb[inside]*b3[keep][inside,2]+wc[inside]*c3[keep][inside,2]
        front[row]=z.max()
clear=mid[:,2]-front
miss=(front==-np.inf)
print("plate triangles %d   no face under them: %d"%(len(clear),miss.sum()))
valid=clear[~miss]
print("clearance mm: min %.3f  1%% %.3f  median %.3f"%(valid.min()*1000,np.percentile(valid,1)*1000,np.median(valid)*1000))
bad=np.nonzero((clear<0)&(~miss))[0]
print("triangles where the face is in front: %d (%.1f%%)"%(len(bad),100.0*len(bad)/len(clear)))
if len(bad):
    order=bad[np.argsort(clear[bad])]
    for k in order[:12]:
        print("   clearance %+.3f mm at x %+.4f y %+.4f  plate z %.4f  face z %.4f"%(clear[k]*1000,mid[k,0],mid[k,1],mid[k,2],front[k]))
    ys=mid[bad][:,1]; xs=mid[bad][:,0]
    print("  affected x %+.4f..%+.4f  y %+.4f..%+.4f"%(xs.min(),xs.max(),ys.min(),ys.max()))
    import collections
    hist=collections.Counter(np.round(ys[bad],3))
    print("  worst rows:",sorted(hist.items(), key=lambda kv:-kv[1])[:12])
