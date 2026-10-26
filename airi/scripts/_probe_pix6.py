import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
import numpy as np
from PIL import Image
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
pic,_=body_texture(a); px=np.asarray(pic)
# the face's front verts at the mouth
bi=next(i for i,m in enumerate(a.document["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
from patch_yxz_mouth_surface import Face
face=Face(a,bi)
sel=(face.positions[:,2]>0.245)&(face.positions[:,1]>0.057)&(face.positions[:,1]<0.067)&(np.abs(face.positions[:,0])<0.025)
uv=face.uvs[sel]
X=np.clip((uv[:,0]*4096).astype(int),0,4095)
Yflip=np.clip(((1-uv[:,1])*4096).astype(int),0,4095)
Yraw=np.clip((uv[:,1]*4096).astype(int),0,4095)
print("flipped rows: colours", px[Yflip,X][:8].tolist())
print("raw rows    : colours", px[Yraw,X][:8].tolist())
print("mean flipped", px[Yflip,X].mean(axis=0).round(1), " mean raw", px[Yraw,X].mean(axis=0).round(1))
Image.fromarray(px[Yraw.min():Yraw.max()+1, X.min():X.max()+1]).resize(((X.max()-X.min())*3,(Yraw.max()-Yraw.min())*3),Image.NEAREST).save("docs/yxz-audit/mouth-atlas-raw.png")
Image.fromarray(px[Yflip.min():Yflip.max()+1, X.min():X.max()+1]).resize(((X.max()-X.min())*3,(Yflip.max()-Yflip.min())*3),Image.NEAREST).save("docs/yxz-audit/mouth-atlas-flip.png")
print("saved")
