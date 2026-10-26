import sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm")); d=a.document
tex = d["textures"][0]; img = d["images"][tex["source"]]
v = d["bufferViews"][img["bufferView"]]
blob = bytes(a.binary[v.get("byteOffset",0):v.get("byteOffset",0)+v["byteLength"]])
p = Image.open(io.BytesIO(blob)).convert("RGB")
W,H = p.size
arr = np.asarray(p)
# plate uv bbox
mi = next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr = d["meshes"][mi]["primitives"][0]
uvs = a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
pos = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
px = uvs[:,0]*W; py=(1-uvs[:,1])*H
x0,x1 = int(px.min()), int(px.max()); y0,y1=int(py.min()),int(py.max())
print("plate uv bbox px", x0,x1,y0,y1, "atlas", W,H)
crop = arr[y0-10:y1+10, x0-10:x1+10]
print("crop unique colors:", np.unique(crop.reshape(-1,3), axis=0)[:12], "n=", len(np.unique(crop.reshape(-1,3),axis=0)))
Image.fromarray(crop).resize((crop.shape[1]*2, crop.shape[0]*2), Image.NEAREST).save("docs/yxz-audit/mouth-region-before.png")
# fit affine  (x,y)->pixel
A = np.zeros((2,3))
Xs = np.column_stack([pos[:,0], pos[:,1], np.ones(len(pos))])
for k,(comp) in enumerate([px,py]):
    sol, *_ = np.linalg.lstsq(Xs, comp, rcond=None)
    A[k]=sol
    resid = Xs@sol - comp
    print("affine dim",k,"resid max %.2f mean %.2f"%(np.abs(resid).max(), np.abs(resid).mean()))
np.save("docs/yxz-audit/mouth-affine.npy", A)
print("centre", pos[:144].mean(axis=0))
