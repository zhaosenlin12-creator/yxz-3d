import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

for f,tag in [("docs/yxz-variants/r138-mouth-safe/yxz.vrm","r138")]:
    a=Asset(Path(f)); d=a.document
    for name in ("YXZ_Mouth","YXZ_MouthCavity"):
        mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")==name)
        pr=d["meshes"][mi]["primitives"][0]
        P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
        I=a.accessor(pr["indices"]).reshape(-1,3)
        c=P[I]
        e=np.maximum.reduce([np.linalg.norm(c[:,1]-c[:,0],axis=1),np.linalg.norm(c[:,2]-c[:,1],axis=1),np.linalg.norm(c[:,0]-c[:,2],axis=1)])
        area=np.linalg.norm(np.cross(c[:,1]-c[:,0], c[:,2]-c[:,0]),axis=1)/2
        print("%s %s: verts %d tris %d  max edge %.5f  p99 edge %.5f  median %.5f"%(tag,name,len(P),len(I),e.max(),np.percentile(e,99),np.median(e)))
        bad=np.nonzero(e>0.002)[0]
        print("   tris with edge>2mm:", len(bad), bad[:10])
        if len(bad):
            t=I[bad[0]]
            print("   example tri verts:", t, "positions:", np.round(P[t],4))
