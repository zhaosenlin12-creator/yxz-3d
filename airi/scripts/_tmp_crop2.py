from PIL import Image
im = Image.open("docs/yxz-audit/source-closeup-r119/source-000.png")
w, h = im.size
print("size", im.size)
box = (int(w*0.32), int(h*0.60), int(w*0.72), int(h*0.80))
crop = im.crop(box).resize((int((box[2]-box[0])*2.2), int((box[3]-box[1])*2.2)), Image.LANCZOS)
crop.save("docs/yxz-audit/source-closeup-r119/mouth-zoom-source.png")
print("saved", crop.size)
