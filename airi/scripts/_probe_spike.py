import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import Front
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
centre=np.array([0.0,0.0621,0.2501])
cand=face.near(centre,0.09)
front=Front(face,cand)
# grid over the plate footprint
xs=np.arange(-0.040,0.0401,0.0005)
ys=np.arange(0.045,0.0791,0.0005)
X,Y=np.meshgrid(xs,ys)
P=np.column_stack([X.reshape(-1),Y.reshape(-1)])
Z=front.query(P[:,0],P[:,1])[0][:,2].reshape(X.shape)
# local max filter over 1mm (2 cells)
pad=np.pad(Z,2,mode="edge")
mx=np.full_like(Z,-np.inf)
for dy in range(5):
    for dx in range(5):
        mx=np.maximum(mx,pad[dy:dy+Z.shape[0],dx:dx+Z.shape[1]])
bump=mx-Z
print("front-most z over the footprint: min %.4f max %.4f"%(Z.min(),Z.max()))
print("bump above the local envelope: max %.3f mm  mean %.3f mm"%(bump.max()*1000,bump.mean()*1000))
ys,xs2=np.nonzero(bump>0.0015)
print("cells that poke above the envelope by >1.5mm:",len(ys))
if len(ys):
    print("   x %+.4f..%+.4f  y %+.4f..%+.4f"%(xs2.min()*0.0005-0.04,xs2.max()*0.0005-0.04,ys.min()*0.0005+0.045,ys.max()*0.0005+0.045))
np.save("docs/yxz-audit/mouth-frontz.npy",Z)
