import sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a=Asset(Path("docs/yxz-variants/r141-mouth/yxz.vrm")); d=a.document
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
P=a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
N=a.accessor(pr["attributes"]["NORMAL"]).astype(np.float64)
RINGS,SEG=28,144
g=P.reshape(RINGS,SEG,3)
x=g[:,:,0]; y=g[:,:,1]; z=g[:,:,2]
# top view, colour by z
W=700; H=320
def to_px(xx,yy):
    return (int((xx+0.05)/0.10*W), int((0.095-yy)/0.06*H))
img=np.zeros((H,W,3),dtype=np.uint8); img[:,:]=255
lo,hi=z.min(),z.max()
for r in range(RINGS):
    for s in range(SEG):
        px,py=to_px(x[r,s],y[r,s])
        v=int(255*(z[r,s]-lo)/(hi-lo))
        img[py,px]=(60,120,255-v)
Image.fromarray(img).save("docs/yxz-audit/plate-topview.png")
print("plate z range %.4f..%.4f"%(lo,hi))
# print the radial z profile for segment 72 (top) and 36 (right)
for s in (36,72):
    print("segment",s, [(r, round(float(z[r,s]),4)) for r in range(0,RINGS,2)])
