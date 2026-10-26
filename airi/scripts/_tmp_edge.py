from PIL import Image
import numpy as np
names = ["1-baseline","3-rim-off","4-wide-terminator","7-no-shadow-no-rim"]
box = (60, 430, 660, 700)
for n in names:
    im = Image.open("docs/yxz-audit/defect-fix-r121/%s-face.png" % n).convert("RGB")
    c = im.crop(box)
    c.resize((c.size[0]*2, c.size[1]*2), Image.LANCZOS).save("docs/yxz-audit/defect-fix-r121/edge-%s.png" % n)
print("ok")
