import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
RINGS,SEG=28,144
inner=P[:SEG]; outer=P[(RINGS-1)*SEG:]
c=inner.mean(axis=0)
print("centre %s"%np.round(c,4))
print("inner ring: x %+.4f..%+.4f (half %.4f) y %+.4f..%+.4f (half %.4f) z %+.4f..%+.4f"%(
  inner[:,0].min(),inner[:,0].max(),(inner[:,0].max()-inner[:,0].min())/2,
  inner[:,1].min(),inner[:,1].max(),(inner[:,1].max()-inner[:,1].min())/2,
  inner[:,2].min(),inner[:,2].max()))
print("outer ring: x %+.4f..%+.4f (half %.4f) y %+.4f..%+.4f (half %.4f) z %+.4f..%+.4f"%(
  outer[:,0].min(),outer[:,0].max(),(outer[:,0].max()-outer[:,0].min())/2,
  outer[:,1].min(),outer[:,1].max(),(outer[:,1].max()-outer[:,1].min())/2,
  outer[:,2].min(),outer[:,2].max()))
names=d["meshes"][mi].get("extras",{}).get("targetNames")
for i,t in enumerate(pr.get("targets",[])):
    D=a.accessor(t["POSITION"]).astype(np.float64)
    ir=(P+D)[:SEG]
    print("morph %-9s: x %+.4f..%+.4f (half %.4f) y %+.4f..%+.4f (half %.4f)"%(names[i],
      ir[:,0].min(),ir[:,0].max(),(ir[:,0].max()-ir[:,0].min())/2,
      ir[:,1].min(),ir[:,1].max(),(ir[:,1].max()-ir[:,1].min())/2))
