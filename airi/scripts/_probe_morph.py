import sys, json
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
for name in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r138-mouth-safe/yxz.vrm"]:
    a = Asset(Path(name)); d=a.document
    for mi,m in enumerate(d["meshes"]):
        if m.get("name")=="YXZ_Mouth":
            prims=m["primitives"]
            print(name)
            for p in prims:
                tg = p.get("targets",[])
                print("  mouth prim targets:", len(tg), [t.get("name") for t in tg])
                print("  extras:", json.dumps(m.get("extras"))[:300])
            print("  node names with morph:")
    print("  animations target names:", [t.get("name") for a_ in [] for t in []])
    names=set()
    for an in d.get("animations",[]):
        for ch in an.get("channels",[]):
            names.add(ch.get("target",{}).get("path"))
    print("  anim paths:", names)
    # list all node names
    print("  nodes:", [n.get("name") for n in d["nodes"]][:40])
