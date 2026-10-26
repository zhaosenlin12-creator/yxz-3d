import sys, json
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
a = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm"))
d = a.document
print("top keys:", list(d.keys()))
print("images:", json.dumps(d.get("images"))[:400])
print("textures:", json.dumps(d.get("textures"))[:400])
print("samplers:", json.dumps(d.get("samplers"))[:300])
print("materials:", [m.get("name") for m in d["materials"]])
for m in d["materials"]:
    if m.get("name") in ("YXZ_MouthPlate",):
        print("PLATE MAT:", json.dumps(m)[:1200])
b = next(m for m in d["materials"] if str(m.get("name","")).startswith("tripo_material"))
print("BODY MAT:", json.dumps(b)[:1600])
