import sys, io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset

a = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm")); d=a.document
tex = d["textures"][0]; img = d["images"][tex["source"]]
v = d["bufferViews"][img["bufferView"]]
p = Image.open(io.BytesIO(bytes(a.binary[v.get("byteOffset",0):v.get("byteOffset",0)+v["byteLength"]]))).convert("RGB")
W,H=p.size
mi = next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr = d["meshes"][mi]["primitives"][0]
uvs = a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
pos = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
SEG=144
px = uvs[:,0]*W; py=(1-uvs[:,1])*H
print("first 8 inner pts (px,py) and 3d:")
for i in range(0,SEG,18):
    print("  %6.1f %6.1f   %+.4f %+.4f"%(px[i],py[i],pos[i][0],pos[i][1]))
# draw loops for every ring
im = p.copy(); dr = ImageDraw.Draw(im)
cols = [(255,0,0),(0,200,0),(0,0,255),(255,160,0),(255,0,255)]
for r in range(0,28,4):
    s = slice(r*SEG,(r+1)*SEG)
    pts = list(zip(px[s], py[s]))+[(px[r*SEG],py[r*SEG])]
    dr.line(pts, fill=cols[r//4], width=3)
im.crop((1860,975,2080,1180)).resize((660,615), Image.NEAREST).save("docs/yxz-audit/uv-loops.png")
print("saved")
