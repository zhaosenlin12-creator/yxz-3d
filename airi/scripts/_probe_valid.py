import sys, json
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
SIZE = {5120:1,5121:1,5122:2,5123:2,5125:4,5126:4}
ITEM = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}
p = Path("docs/yxz-variants/r138-mouth-safe/yxz-texture.vrm")
a = Asset(p); d=a.document
n=len(a.binary)
bad=0
for i,acc in enumerate(d["accessors"]):
    if "bufferView" not in acc: continue
    bv=d["bufferViews"][acc["bufferView"]]
    need = acc["count"]*ITEM[acc["type"]]*SIZE[acc["componentType"]]
    if bv.get("byteLength",0) < need:
        bad+=1; print("SHORT accessor",i,acc["type"],acc["componentType"],acc["count"],"need",need,"bvlen",bv.get("byteLength"))
print("short accessors:",bad)
for i,im in enumerate(d["images"]):
    bv=d["bufferViews"][im["bufferView"]]
    print("image",i,im.get("name"),"off",bv.get("byteOffset"),"len",bv.get("byteLength"),"end",bv.get("byteOffset",0)+bv.get("byteLength",0))
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr=d["meshes"][mi]["primitives"][0]
for k,idx in pr["attributes"].items():
    print("attr",k,"accessor",idx, json.dumps(d["accessors"][idx]))
print("plate mat", json.dumps(d["materials"][next(i for i,m in enumerate(d["materials"]) if m.get("name")=="YXZ_MouthPlate")]))
print("textures", json.dumps(d["textures"]))
print("images", json.dumps(d["images"]))
