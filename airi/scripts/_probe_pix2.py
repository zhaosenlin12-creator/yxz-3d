import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
import numpy as np
p="docs/yxz-variants/r143-mouth/yxz.vrm"
a=Asset(Path(p)); d=a.document
for i,m in enumerate(d["meshes"]):
    n=str(m.get("name",""))
    if n in ("YXZ_Mouth","YXZ_MouthCavity"):
        for pr in m["primitives"]:
            P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
            print(n,"bbox x %+.4f..%+.4f y %+.4f..%+.4f z %+.4f..%+.4f"%(P[:,0].min(),P[:,0].max(),P[:,1].min(),P[:,1].max(),P[:,2].min(),P[:,2].max()))
            UV=a.accessor(pr["attributes"]["TEXCOORD_0"])
            print("   uv x %.4f..%.4f y %.4f..%.4f"%(UV[:,0].min(),UV[:,0].max(),UV[:,1].min(),UV[:,1].max()))
pic,_=body_texture(a); px=np.asarray(pic)
# find maroon pixels like the mouth paint
target=np.array([62,18,24])
d2=np.abs(px.astype(int)-target).sum(axis=2)
ys,xs=np.nonzero(d2<40)
print("maroon-ish pixels:",len(ys))
if len(ys): print("  bbox x %d..%d y %d..%d"%(xs.min(),xs.max(),ys.min(),ys.max()))
