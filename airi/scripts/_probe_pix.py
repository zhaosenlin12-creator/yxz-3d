import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_texture import body_texture
from patch_yxz_mouth_surface import Asset
import numpy as np
for p in ["packages/stage-ui-three/src/assets/vrm/models/yxz.vrm","docs/yxz-variants/r143-mouth/yxz.vrm"]:
    a=Asset(Path(p))
    pic,_=body_texture(a)
    px=np.asarray(pic)
    reg=px[998:1158,1882:2057]
    print(p)
    print("   region mean rgb",reg.reshape(-1,3).mean(axis=0).round(1),"min",reg.reshape(-1,3).min(axis=0),"max",reg.reshape(-1,3).max(axis=0))
    print("   dark pixels (<120):", int((reg.min(axis=2)<120).sum()), "of", reg.shape[0]*reg.shape[1])
