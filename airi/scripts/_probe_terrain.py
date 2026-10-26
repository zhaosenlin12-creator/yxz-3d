import numpy as np
from PIL import Image
Z=np.load("docs/yxz-audit/mouth-frontz.npy")
print(Z.shape, Z.min(), Z.max())
img=((Z-Z.min())/(Z.max()-Z.min())*255).astype("uint8")
Image.fromarray(img).resize((Z.shape[1]*3,Z.shape[0]*3),Image.NEAREST).save("docs/yxz-audit/mouth-terrain.png")
# a sideways profile down the middle
print("profile at the centre column (x=0):")
c=Z.shape[1]//2
for r in range(0,Z.shape[0],6):
    print("   y %+.4f  z %.4f"%(0.045+r*0.0005, Z[r,c]))
