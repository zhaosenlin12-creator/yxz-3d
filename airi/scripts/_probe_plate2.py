import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
for path in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm",
             "docs/yxz-audit/candidates/yxz-deployed-preRestore.vrm"]:
    p=Path(path)
    if not p.exists():
        print("missing",p); continue
    a=Asset(p); d=a.document
    mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
    pr=d["meshes"][mi]["primitives"][0]
    P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
    R=P.reshape(28,144,3)
    print("==",path)
    for r in (0,1,13,27):
        print("  ring %2d: x %+.4f..%+.4f y %+.4f..%+.4f z %+.4f..%+.4f"%(r,R[r,:,0].min(),R[r,:,0].max(),R[r,:,1].min(),R[r,:,1].max(),R[r,:,2].min(),R[r,:,2].max()))
    # head bbox of body
    bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
    B=a.accessor(d["meshes"][bi]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
    print("  body bbox x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f"%(B[:,0].min(),B[:,0].max(),B[:,1].min(),B[:,1].max(),B[:,2].min(),B[:,2].max()))
