import sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm")); d=a.document
tex = d["textures"][0]; img = d["images"][tex["source"]]
v = d["bufferViews"][img["bufferView"]]
p = Image.open(io.BytesIO(bytes(a.binary[v.get("byteOffset",0):v.get("byteOffset",0)+v["byteLength"]]))).convert("RGB")
W,H = p.size; arr=np.asarray(p).astype(float)
mi = next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr = d["meshes"][mi]["primitives"][0]
uvs = a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
pos = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
RINGS,SEG = 28,144
px = uvs[:,0]*W; py=(1-uvs[:,1])*H
inner = slice(0,SEG)
print("inner ring pixel bbox x %.0f..%.0f y %.0f..%.0f"%(px[inner].min(),px[inner].max(),py[inner].min(),py[inner].max()))
print("inner ring 3d bbox x %.4f..%.4f y %.4f..%.4f z %.4f..%.4f"%(pos[inner][:,0].min(),pos[inner][:,0].max(),pos[inner][:,1].min(),pos[inner][:,1].max(),pos[inner][:,2].min(),pos[inner][:,2].max()))
print("outer ring pixel bbox x %.0f..%.0f y %.0f..%.0f"%(
  px[(RINGS-1)*SEG:].min(),px[(RINGS-1)*SEG:].max(),py[(RINGS-1)*SEG:].min(),py[(RINGS-1)*SEG:].max()))
# darkness profile along vertical through the mouth centre x
cx = int((px[inner].min()+px[inner].max())/2)
col = arr[930:1200, cx]
dark = 255*3 - col.sum(axis=1)
print("darkest rows in column x=%d:"%cx, [(930+i, round(float(d),1)) for i in np.argsort(dark)[-8:]])
# row profile across the dark band
r = 1102
row = arr[r, 1850:2100]
d2 = 255*3-row.sum(axis=1)
print("row 1102 darkest x:", [(1850+i, round(float(d),1)) for i in np.argsort(d2)[-8:]])
