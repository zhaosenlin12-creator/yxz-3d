import sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import heightmap

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
P=a.accessor(d["meshes"][mi]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
centre=P[:144].mean(axis=0)
cand=face.near(centre,0.09)
xs,ys,depth,hit=heightmap(face,centre,0.060,0.030,0.0002,cand)
finite=np.isfinite(depth)
z=np.where(finite, depth, np.nan)
lo=np.nanmin(z); hi=np.nanmax(z)
print("depth range %.4f..%.4f"%(lo,hi))
img=((hi-z)/(hi-lo)*255).astype(np.uint8)
Image.fromarray(img).resize((601*2//2, 301), Image.NEAREST).save("docs/yxz-audit/depth-map.png")
# how many cells are on the "deep" layer
print("cells with depth < 0.248:", int((depth<0.248).sum()), "of", depth.size)
ys2,xs2=np.nonzero(depth<0.248)
if len(xs2): print("  their x %.4f..%.4f y %.4f..%.4f"%(xs[xs2].min(),xs[xs2].max(),ys[ys2].min(),ys[ys2].max()))
print("cells with depth >= 0.248:", int((depth>=0.248).sum()))
