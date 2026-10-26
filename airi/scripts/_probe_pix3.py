import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset, Face
import numpy as np
a=Asset(Path("docs/yxz-variants/r143-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
pic,_=body_texture(a); px=np.asarray(pic)
sel=(np.abs(face.positions[:,0])<0.020)&(face.positions[:,1]>0.058)&(face.positions[:,1]<0.066)
print("face verts at the mouth:",sel.sum())
uv=face.uvs[sel]
xs=np.clip((uv[:,0]*4096).astype(int),0,4095)
ys=np.clip(((1-uv[:,1])*4096).astype(int),0,4095)
print("their atlas pixels: x %d..%d  y %d..%d"%(xs.min(),xs.max(),ys.min(),ys.max()))
cols=px[ys,xs]
print("mean colour there:",cols.mean(axis=0).round(1))
print("darkest:",cols[np.argsort(cols.sum(axis=1))[:5]])
# whole-atlas maroon search
r=px[:,:,0].astype(int); g=px[:,:,1].astype(int); b=px[:,:,2].astype(int)
mask=(r>g+25)&(r>b+10)&(r<160)
ys2,xs2=np.nonzero(mask)
print("maroon pixels in the whole atlas:",len(ys2))
if len(ys2):
    print("  bbox x %d..%d y %d..%d"%(xs2.min(),xs2.max(),ys2.min(),ys2.max()))
    print("  sample colours:",px[ys2[:5],xs2[:5]])
