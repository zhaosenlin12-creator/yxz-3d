import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import heightmap

a=Asset(Path("docs/yxz-variants/r142-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
I=a.accessor(pr["indices"]).reshape(-1,3)
c=P[I]; cen=c.mean(axis=1)
xs,ys,depth,hit=heightmap(face,cen[0],0.060,0.030,0.0002,face.near(cen[0],0.09))
col=np.clip(((cen[:,0]-xs[0])/(xs[1]-xs[0])).astype(int),0,len(xs)-1)
row=np.clip(((cen[:,1]-ys[0])/(ys[1]-ys[0])).astype(int),0,len(ys)-1)
face_z=depth[row,col]
plate_z=cen[:,2]
clear=plate_z-face_z
print("clearance (plate - face) over %d triangles: min %.5f  1%% %.5f  median %.5f"%(len(clear), clear.min(), np.percentile(clear,1), np.median(clear)))
bad=np.nonzero(clear<0.0)[0]
print("triangles where the face pokes through:", len(bad))
if len(bad):
    k=bad[np.argmin(clear[bad])]
    print("worst: clearance %.5f at x %+.4f y %+.4f z %.4f (face z %.4f)"%(clear[k], cen[k][0],cen[k][1],cen[k][2],face_z[k]))
    xs_b=cen[bad][:,0]; ys_b=cen[bad][:,1]
    print("  affected x %.4f..%.4f y %.4f..%.4f"%(xs_b.min(),xs_b.max(),ys_b.min(),ys_b.max()))
    # histogram of the worst region
    for lo,hi in [(0.10,0.12),(0.12,0.14),(0.14,0.16)]:
        sel=(ys_b>lo)&(ys_b<hi)
        print("   band y %.2f..%.2f: %d tris"%(lo,hi,sel.sum()))

