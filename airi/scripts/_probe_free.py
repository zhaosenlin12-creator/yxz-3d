import sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, "scripts")
from patch_yxz_mouth_surface import Asset

asset = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm"))
doc = asset.document
mat = next(m for m in doc["materials"] if str(m.get("name","")).startswith("tripo_material"))
ti = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
img = doc["images"][ti]
view = doc["bufferViews"][img["bufferView"]]
blob = bytes(asset.binary[view.get("byteOffset",0):view.get("byteOffset",0)+view["byteLength"]])
p = Image.open(io.BytesIO(blob))
print("atlas", p.size, p.mode)

# used mask over whole atlas, excluding YXZ_Mouth
W,H = p.size
used = np.zeros((H,W), dtype=bool)
names = []
for mesh in doc["meshes"]:
    nm = mesh.get("name","")
    names.append(nm)
    if nm == "YXZ_Mouth":
        continue
    for prim in mesh.get("primitives", []):
        att = prim.get("attributes", {})
        if "TEXCOORD_0" not in att: continue
        uvs = asset.accessor(att["TEXCOORD_0"]).astype(np.float64)
        idx = asset.accessor(prim["indices"]).reshape(-1,3)
        px = uvs[idx][:,:,0]*W
        py = (1-uvs[idx][:,:,1])*H
        for t in range(len(px)):
            x0=int(max(0,np.floor(px[t].min()))); x1=int(min(W,np.ceil(px[t].max())+1))
            y0=int(max(0,np.floor(py[t].min()))); y1=int(min(H,np.ceil(py[t].max())+1))
            if x1<=x0 or y1<=y0: continue
            used[y0:y1, x0:x1] = True
print("mesh names:", names)
print("used fraction %.3f" % used.mean())
free = ~used
print("free fraction %.3f" % free.mean())

# largest free rectangle with 176x161 (padded: 192x177)
need_w, need_h = 176+16, 161+16
best=None
for y in range(0, H-need_h+1, 4):
    for x in range(0, W-need_w+1, 4):
        if not free[y:y+need_h, x:x+need_w].any():
            print("FREE RECT at x=%d y=%d" % (x,y))
            best=(x,y); break
    if best: break
if not best:
    # try smaller
    for need_w2, need_h2 in [(176,161),(120,120),(64,64),(32,32)]:
        found=None
        for y in range(0, H-need_h2+1, 4):
            for x in range(0, W-need_w2+1, 4):
                if not free[y:y+need_h2, x:x+need_w2].any():
                    found=(x,y); break
            if found: break
        print("need %dx%d -> %s" % (need_w2, need_h2, found))
        if found: break
