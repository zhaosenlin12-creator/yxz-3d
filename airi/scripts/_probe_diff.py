from PIL import Image
import numpy as np
a=np.asarray(Image.open("docs/yxz-audit/parts-r140/all.png").convert("RGB")).astype(int)
b=np.asarray(Image.open("docs/yxz-audit/parts-r140/no-plate.png").convert("RGB")).astype(int)
d=np.abs(a-b).sum(axis=2)
print("diff: max %d  mean %.2f  pixels>20: %d (%.2f%%)"%(d.max(), d.mean(), (d>20).sum(), 100*(d>20).mean()))
Image.fromarray(np.clip(d*4,0,255).astype(np.uint8)).save("docs/yxz-audit/plate-diff.png")
ys,xs=np.nonzero(d>20)
if len(xs): print("changed bbox x %d..%d y %d..%d"%(xs.min(),xs.max(),ys.min(),ys.max()))
