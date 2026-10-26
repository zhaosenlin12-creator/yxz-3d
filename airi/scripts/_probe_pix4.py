import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
import numpy as np
for name in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r143-mouth/yxz.vrm"]:
    a=Asset(Path(name))
    pic,_=body_texture(a); px=np.asarray(pic).astype(int)
    for t in ([30,8,12],[62,18,24]):
        m=(np.abs(px-np.array(t)).sum(axis=2)<30)
        ys,xs=np.nonzero(m)
        print(name, t, "count",len(ys), ("bbox x %d..%d y %d..%d"%(xs.min(),xs.max(),ys.min(),ys.max())) if len(ys) else "")
    # every texture in the file
    for i,t in enumerate(d["textures"] if False else a.document["textures"]):
        img=a.document["images"][t["source"]]
        v=a.document["bufferViews"][img["bufferView"]]
        print("   texture",i,"image",img.get("name"),img["mimeType"],"bytes",v["byteLength"])
