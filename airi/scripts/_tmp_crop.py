from PIL import Image
import os
src = "docs/yxz-audit/defect-fix-r120/1-baseline-face.png"
im = Image.open(src)
print("size", im.size)
w, h = im.size
box = (int(w*0.20), int(h*0.55), int(w*0.78), int(h*0.92))
crop = im.crop(box).resize((int((box[2]-box[0])*2.2), int((box[3]-box[1])*2.2)), Image.LANCZOS)
crop.save("docs/yxz-audit/defect-fix-r120/mouth-zoom-baseline.png")
print("saved", crop.size)
