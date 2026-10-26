import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
import numpy as np
a=Asset(Path("docs/yxz-variants/r143-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
sel=(np.abs(face.positions[:,0])<0.030)&(face.positions[:,1]>0.046)&(face.positions[:,1]<0.080)
print("verts in the plate footprint:",sel.sum())
uv=face.uvs[sel]; pos=face.positions[sel]
order=np.argsort(pos[:,1])
for i in order:
    print("  x %+.4f y %+.4f z %+.4f  uv %.4f %.4f  px %4d %4d"%(pos[i,0],pos[i,1],pos[i,2],uv[i,0],uv[i,1],uv[i,0]*4096,(1-uv[i,1])*4096))
