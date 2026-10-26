import sys, json
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset
for f in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r138-mouth-safe/yxz.vrm"]:
    a=Asset(Path(f)); d=a.document
    mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
    pr=d["meshes"][mi]["primitives"][0]
    for key in ("TEXCOORD_0","POSITION","NORMAL"):
        spec=d["accessors"][pr["attributes"][key]]
        print(f.split("/")[-1], key, json.dumps(spec))
