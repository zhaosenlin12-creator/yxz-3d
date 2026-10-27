"""Camera upload endpoint for Cartoon Print Studio."""
# 在 server.py 的 line 2001 后添加此代码：

"""
@app.post("/api/upload-image", status_code=201)
async def upload_image(image: UploadFile = File(...), source: str = Form("camera")):
    '''Upload image from camera or file picker, analyze with vision model.

    Returns a session ID and AI-generated description to pre-fill chat context.
    '''
    # Validate file type
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(415, "只支持上传图片文件")

    # Create session
    sid = uuid.uuid4().hex[:12]
    previews = os.path.join(session_dir(sid), "previews")
    os.makedirs(previews, exist_ok=True)

    # Save uploaded image
    img_path = os.path.join(previews, "img_0.png")
    size = await _save_uploaded_file(image, img_path, 15 * 1024 * 1024)  # 15MB limit

    # Convert to PNG if needed
    try:
        from PIL import Image as PILImage
        with PILImage.open(img_path) as decoded:
            decoded.load()
            if max(decoded.size) > 4096:
                raise HTTPException(413, "图片尺寸过大，请使用 4096x4096 以下的图片")
            if decoded.mode not in ("RGBA", "RGB"):
                decoded = decoded.convert("RGBA")
            decoded.save(img_path, "PNG")
            width, height = decoded.size
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"图片无法读取：{exc}") from exc

    # Analyze image with vision model
    description = "你的照片"
    try:
        # Use LLM with vision to describe the image
        import llm_client
        vision_prompt = "请用一句话描述这张图片的主要内容，重点说明适合制作什么样的创意作品。控制在20字以内。"

        # Read image as base64
        with open(img_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()

        # Call vision API (if available)
        try:
            vision_result = llm_client.vision_chat(vision_prompt, img_base64)
            if vision_result and len(vision_result) > 0:
                description = vision_result.strip()
        except Exception as vision_err:
            print(f"[upload-image] vision analysis failed: {vision_err}")
            # Fallback to simple description
            description = f"{width}x{height} 的照片"

    except Exception as analyze_err:
        print(f"[upload-image] analysis failed: {analyze_err}")
        description = "你上传的照片"

    # Save source metadata
    with open(os.path.join(DATA, sid, "_source.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "source": source,
            "created_at": int(time.time()),
            "width": width,
            "height": height,
            "size_bytes": size,
        }, handle, ensure_ascii=False)

    return {
        "session_id": sid,
        "image_path": f"/api/data/{sid}/previews/img_0.png",
        "description": description,
        "width": width,
        "height": height,
        "message": "照片已上传成功",
    }
"""
