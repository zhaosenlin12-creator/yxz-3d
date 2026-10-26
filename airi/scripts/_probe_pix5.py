import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset, Face
import numpy as np
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
pic,_=body_texture(a); px=np.asarray(pic)
d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
sel=(face.positions[:,2]>0.24)&(face.positions[:,1]>0.058)&(face.positions[:,1]<0.066)&(np.abs(face.positions[:,0])<0.02)
print("front verts at the mouth:",sel.sum())
for i in np.nonzero(sel)[0]:
    uv=face.uvs[i]; X=int(uv[0]*4096); Y=int((1-uv[1])*4096)
    X=min(max(X,0),4095); Y=min(max(Y,0),4095)
    print("  x %+.4f y %+.4f z %+.4f  uv %.4f %.4f  px (%4d,%4d) rgb %s"%(face.positions[i,0],face.positions[i,1],face.positions[i,2],uv[0],uv[1],X,Y,px[Y,X]))
