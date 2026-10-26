import json, sys
sys.path.insert(0, "scripts")
from glb_json import read_glb
doc, data = read_glb("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
print("meshes:")
for i, m in enumerate(doc["meshes"]):
    prims = m.get("primitives", [])
    targets = sum(len(p.get("targets", [])) for p in prims)
    names = m.get("extras", {}).get("targetNames", [])
    print("  [%d] %-22s prims=%d targets=%d names=%s" % (i, m.get("name"), len(prims), targets, names))
print("materials:", [m.get("name") for m in doc.get("materials", [])])
print("nodes:", [(i, n.get("name")) for i, n in enumerate(doc["nodes"])][:60])
print("skins:", [(s.get("name"), len(s.get("joints", []))) for s in doc.get("skins", [])])
