import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
N=a.accessor(pr["attributes"]["NORMAL"]).astype(np.float64)
I=a.accessor(pr["indices"]).reshape(-1,3)
c=P[I]
geo=np.cross(c[:,1]-c[:,0],c[:,2]-c[:,0]); geo/=np.linalg.norm(geo,axis=1,keepdims=True)
steep=np.abs(geo[:,2])<0.5
print("triangles with a steep surface (|geo.z|<0.5):", steep.sum(), "of", len(I))
cen=c.mean(axis=1)
if steep.sum():
    print("  their x %.4f..%.4f y %.4f..%.4f"%(cen[steep][:,0].min(),cen[steep][:,0].max(),cen[steep][:,1].min(),cen[steep][:,1].max()))
    print("  sample positions:", np.round(cen[steep][:8],4))
# z spread of the plate
print("plate z range %.4f..%.4f"%(P[:,2].min(),P[:,2].max()))
# per-ring z profile at segment 0
for r in range(0,28,3):
    seg=r*144
    print("  ring %2d z %.4f  x %+.4f y %+.4f | ring1 %2d z %.4f x %+.4f"%(r,P[seg,2],P[seg,0],P[seg,1],r+1,P[(r+1)*144,2],P[(r+1)*144,0]))
# how far is the plate from the face at the same xy? compare with the depth map
from patch_yxz_mouth_surface import Face
from rebuild_yxz_mouth import heightmap, sample_surface
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
centre=P[:144].mean(axis=0)
cand=face.near(centre,0.09)
xs,ys,depth,hit=heightmap(face,centre,0.060,0.030,0.0002,cand)
surf,nrm,uvs=sample_surface(face,xs,ys,hit,P[:,0],P[:,1])
gap=(P-surf)[:,2]
print("plate - face z gap: min %.5f max %.5f mean %.5f"%(gap.min(),gap.max(),gap.mean()))
print("  verts with gap<0.0002:", int((gap<0.0002).sum()))
