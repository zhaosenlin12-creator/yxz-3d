import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset, Face
import numpy as np
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
pic,_=body_texture(a); px=np.asarray(pic).astype(int)
bi=next(i for i,m in enumerate(a.document["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
sel=(face.positions[:,2]>0.24)&(face.positions[:,1]>0.040)&(face.positions[:,1]<0.082)&(np.abs(face.positions[:,0])<0.045)
uv=face.uvs[sel]; pos=face.positions[sel]
X=np.clip((uv[:,0]*4096).astype(int),0,4095); Y=np.clip((uv[:,1]*4096).astype(int),0,4095)
cols=px[Y,X]
red=(cols[:,0]>cols[:,1]+25)&(cols[:,0]<190)
print("verts on the painted mouth:",red.sum())
for i in np.nonzero(red)[0][:40]:
    print("   x %+.4f y %+.4f z %+.4f   rgb %s"%(pos[i,0],pos[i,1],pos[i,2],cols[i].tolist()))
print("y range of the painted mouth: %.4f .. %.4f"%(pos[red][:,1].min(),pos[red][:,1].max()))
print("x range: %.4f .. %.4f"%(pos[red][:,0].min(),pos[red][:,0].max()))
