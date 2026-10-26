import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import heightmap

a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
centre=np.array([0.0,0.0621,0.2501])
cand=face.near(centre,0.09)
xs,ys,depth,hit=heightmap(face,centre,0.060,0.030,0.0002,cand)
col=int((0.0-xs[0])/(xs[1]-xs[0]))
print("vertical profile at x=0 (y from %.4f to %.4f):"%(ys[0],ys[-1]))
for r in range(0,len(ys),4):
    print("  y %+.4f  z %.4f  tri %d"%(ys[r], depth[r,col], hit[r,col]))
