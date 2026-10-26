import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
for i,m in enumerate(d["meshes"]):
    n=str(m.get("name",""))
    for p in m["primitives"]:
        P=a.accessor(p["attributes"]["POSITION"]).astype(np.float64)
        print("%-52s prim%d verts %7d  x %+.3f..%+.3f y %+.3f..%+.3f z %+.3f..%+.3f"%(n[:52],i,len(P),P[:,0].min(),P[:,0].max(),P[:,1].min(),P[:,1].max(),P[:,2].min(),P[:,2].max()))
