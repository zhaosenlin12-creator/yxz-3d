import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

src = Path("docs/yxz-variants/r141-mouth/yxz-texture.vrm")
dst = Path("docs/yxz-variants/r141-mouth/yxz-flatnormal.vrm")
a = Asset(src); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
N=a.accessor(pr["attributes"]["NORMAL"]).astype(np.float64)
flat=np.zeros_like(N); flat[:,2]=1.0
d["accessors"][pr["attributes"]["NORMAL"]]["bufferView"]=a.add_accessor(flat,"VEC3",34962)
# also morph target normals
for t in pr.get("targets",[]):
    if "NORMAL" in t:
        dn=a.accessor(t["NORMAL"]).astype(np.float64)
        d["accessors"][t["NORMAL"]]["bufferView"]=a.add_accessor(np.zeros_like(dn),"VEC3")
a.save(dst)
print("wrote", dst)
