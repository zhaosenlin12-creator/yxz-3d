import sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

for f,tag in [("docs/yxz-variants/r141-mouth/yxz-texture.vrm","r141")]:
    a=Asset(Path(f)); d=a.document
    for im in d["images"]:
        if im.get("name")!="YXZ_MouthPlateTex": continue
        bv=d["bufferViews"][im["bufferView"]]
        blob=bytes(a.binary[bv.get("byteOffset",0):bv.get("byteOffset",0)+bv["byteLength"]])
        p=Image.open(io.BytesIO(blob)).convert("RGB")
        print(tag, "plate texture", p.size)
        p.save("docs/yxz-audit/plate-texture.png")
        arr=np.asarray(p)
        print("  unique colors:", len(np.unique(arr.reshape(-1,3),axis=0)))
