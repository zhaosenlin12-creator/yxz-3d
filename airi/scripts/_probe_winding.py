import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

for f in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r138-mouth-safe/yxz.vrm"]:
    a=Asset(Path(f)); d=a.document
    mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
    pr=d["meshes"][mi]["primitives"][0]
    P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
    N=a.accessor(pr["attributes"]["NORMAL"]).astype(np.float64)
    I=a.accessor(pr["indices"]).reshape(-1,3)
    c=P[I]
    geo=np.cross(c[:,1]-c[:,0], c[:,2]-c[:,0])
    n=geo/np.linalg.norm(geo,axis=1,keepdims=True)
    vn=N[I].mean(axis=1)
    vn=vn/np.linalg.norm(vn,axis=1,keepdims=True)
    dot=(n*vn).sum(axis=1)
    print(f.split("/")[-1], "triangles", len(I), "dot(geo,vertexNormal) mean %.3f  frac>0 %.3f"%(dot.mean(), (dot>0).mean()))
    # what does the plate's own normal vs radial direction look like: does the normal point outward from the head (+z)?
    print("   mean vertex normal z %.3f ; geo z %.3f"%(N[:,2].mean(), n[:,2].mean()))
