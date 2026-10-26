import sys, json
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
for m in d["materials"]:
    print("==",m.get("name"))
    print(json.dumps({k:v for k,v in m.items() if k!="name"},ensure_ascii=False)[:1200])
    print()
