import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
U=a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
centre=P[:144].mean(axis=0)
z=P[:,2]
print("plate z: %.4f..%.4f"%(z.min(),z.max()))
import collections
hist,edges=np.histogram(z, bins=20)
for h,e in zip(hist,edges): print("  z %.4f : %d"%(e,h))
sel = z>0.2545
print("verts in front of the face surface:", sel.sum())
if sel.sum():
    print("  x %.4f..%.4f y %.4f..%.4f"%(P[sel][:,0].min(),P[sel][:,0].max(),P[sel][:,1].min(),P[sel][:,1].max()))
    print("  distance from mouth centre: %.4f..%.4f"%(np.linalg.norm(P[sel][:,:2]-centre[:2],axis=1).min(), np.linalg.norm(P[sel][:,:2]-centre[:2],axis=1).max()))
    pu=U[sel]
    print("  their atlas px x %.0f..%.0f y %.0f..%.0f"%(pu[:,0].min()*4096,pu[:,0].max()*4096,(1-pu[:,1].min())*4096,(1-pu[:,1].max())*4096))
    for i in np.nonzero(sel)[0][:6]:
        print("   v%5d pos %s uv px %.0f %.0f"%(i,np.round(P[i],4),U[i][0]*4096,(1-U[i][1])*4096))
# the rest
sel2 = z<=0.2545
pu=U[sel2]
print("normal plate verts atlas px x %.0f..%.0f y %.0f..%.0f"%(pu[:,0].min()*4096,pu[:,0].max()*4096,(1-pu[:,1].min())*4096,(1-pu[:,1].max())*4096))
