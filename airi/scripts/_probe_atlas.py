import sys, io
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
import numpy as np
from PIL import Image
p=Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
a=Asset(p)
pic,_=body_texture(a)
print("atlas",pic.size)
crop=pic.crop((1780,900,2160,1230)).resize((760,660),Image.NEAREST)
crop.save("docs/yxz-audit/mouth-atlas-deployed.png")
print("saved")
