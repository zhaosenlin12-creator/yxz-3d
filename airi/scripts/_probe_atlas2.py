import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
from PIL import Image
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
pic,_=body_texture(a)
c=pic.crop((1860,1000,2040,1180)).resize((720,720),Image.NEAREST)
c.save("docs/yxz-audit/mouth-atlas-exact.png")
print("ok")
