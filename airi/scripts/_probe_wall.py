import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
T=face.triangles
corners=face.positions[T]
n=np.cross(corners[:,1]-corners[:,0],corners[:,2]-corners[:,0])
ln=np.linalg.norm(n,axis=1,keepdims=True); ln[ln<1e-14]=1
n=n/ln
cen=corners.mean(axis=1)
region=(cen[:,2]>0.235)&(cen[:,1]>0.044)&(cen[:,1]<0.080)&(np.abs(cen[:,0])<0.043)
steep=region&(np.abs(n[:,2])<0.45)
print("triangles in the plate footprint:",region.sum())
print("of those, nearly upright (|n.z|<0.45):",steep.sum())
for k in np.nonzero(steep)[0][:20]:
    print("   tri %d n %s  z span %.4f..%.4f  y %.4f..%.4f"%(k,np.round(n[k],2),corners[k][:,2].min(),corners[k][:,2].max(),corners[k][:,1].min(),corners[k][:,1].max()))
print("vertical extent of those:", np.round(corners[np.nonzero(steep)[0]][:,:,2].max()-corners[np.nonzero(steep)[0]][:,:,2].min(),4)[:20])
