from PIL import Image
import numpy as np
names = ["1-baseline","2-no-shadow","3-rim-off","4-wide-terminator","5-no-outline","6-no-bloom","7-no-shadow-no-rim","8-no-shadow-no-rim-wide"]
imgs = {n: Image.open("docs/yxz-audit/defect-fix-r121/%s-face.png" % n).convert("RGB") for n in names}
base = np.asarray(imgs["1-baseline"], dtype=int)
for n in names[1:]:
    a = np.asarray(imgs[n], dtype=int)
    d = np.abs(a-base).sum(axis=2)
    print("%-24s max=%4d  >30:%7d  >90:%7d" % (n, d.max(), int((d>30).sum()), int((d>90).sum())))
# also check the baseline against itself for jitter
print("base size", imgs["1-baseline"].size)
