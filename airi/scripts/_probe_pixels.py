from PIL import Image
import numpy as np
im = np.asarray(Image.open("docs/yxz-audit/parts-r140/all.png").convert("RGB")).astype(int)
pts = {"plate-left-inside":(300,660),"face-left-outside":(120,660),
       "plate-bottom-inside":(450,690),"face-below":(450,760),
       "plate-upper":(450,480),"face-upper-out":(300,400),
       "plate-right":(760,600),"face-right-out":(880,600)}
for k,(x,y) in pts.items():
    print("%-20s %s"%(k, im[y,x]))
# row profile across the plate edge at y=660
print("row 660:", [(x, tuple(im[660,x])) for x in range(60,340,20)])
