import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import heightmap

for path in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r142-mouth/yxz.vrm"]:
    a=Asset(Path(path)); d=a.document
    mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
    pr=d["meshes"][mi]["primitives"][0]
    P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
    n=len(P); print("==",path,"plate verts",n,"targets",len(pr.get("targets",[])))
    ring=P[:144]
    print("  inner ring: x %+.4f..%+.4f  y %+.4f..%+.4f  z %+.4f..%+.4f"%(ring[:,0].min(),ring[:,0].max(),ring[:,1].min(),ring[:,1].max(),ring[:,2].min(),ring[:,2].max()))
    print("  inner centre:",np.round(ring.mean(axis=0),4))
    outer=P.reshape(-1,144,3)[:,-1,:]
    print("  outer ring: x %+.4f..%+.4f  y %+.4f..%+.4f"%(outer[:,0].min(),outer[:,0].max(),outer[:,1].min(),outer[:,1].max()))
    # where is the mouth painted? look at the atlas crop region
    print("  uv range:", np.round(a.accessor(pr["attributes"]["TEXCOORD_0"]).min(axis=0),4), np.round(a.accessor(pr["attributes"]["TEXCOORD_0"]).max(axis=0),4))
