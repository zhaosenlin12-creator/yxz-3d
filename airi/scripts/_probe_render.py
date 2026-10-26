from PIL import Image
import numpy as np
im=np.asarray(Image.open("docs/yxz-audit/parts-r143/all.png").convert("RGB")).astype(int)
print("image",im.shape)
reg=im[560:660,200:760]
cols=res=reg.reshape(-1,3)
# darkest pixels
s=cols.sum(axis=1)
order=np.argsort(s)
print("darkest 8 samples:")
for i in order[:8]: print("   ",cols[i])
print("face sample:",im[800,500], im[450,500])
