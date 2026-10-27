import json, sys
sys.path.insert(0, "scripts")
from patch_yxz_mouth_surface import Asset
a = Asset("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
d = a.document
print("LOOKAT", json.dumps(d.get("extensions",{}).get("VRMC_vrm_lookAt",{}), ensure_ascii=False))
print("--- nodes ---")
for i,n in enumerate(d.get("nodes",[])):
    if n.get("name"):
        print(i, n.get("name"), "children", n.get("children"), "t", n.get("translation"), "s", n.get("scale"))
