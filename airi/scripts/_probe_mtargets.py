import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
import numpy as np
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
d=a.document
for i,m in enumerate(d["meshes"]):
    n=str(m.get("name",""))
    if not n.startswith("tripo_mesh") and n not in ("YXZ_Mouth","YXZ_MouthCavity"): continue
    tg=m.get("extras",{}).get("targetNames")
    for p in m["primitives"]:
        t=p.get("targets",[])
        print(n, "prims",len(m["primitives"]), "targets",len(t), "names",tg)
        if t:
            for k,tt in enumerate(t[:3]):
                print("   target",k, {kk:(vv.get("type"),vv.get("count")) for kk,vv in tt.items()})
    print("  materials:", [d["materials"][p["material"]].get("name") for p in m["primitives"]])
