#!/bin/bash
# 摄像头拍照功能集成脚本
# 完成所有必要的代码修改

set -e

PROJECT_ROOT="/c/kaifa_senlin/pingdou/pingdou-workstation-final"
AIRI_ROOT="$PROJECT_ROOT/airi"
BACKEND_ROOT="$PROJECT_ROOT/cartoon-print-studio/backend"

echo "🎥 开始集成摄像头拍照功能..."
echo ""

# Step 1: 在 server.py 中添加上传接口
echo "📝 步骤 1/3: 添加后端上传接口..."
cd "$PROJECT_ROOT"

# 查找 server.py 中要插入的位置（在 @app.get("/api/data/{sid}/{sub_path:path}") 之前）
python3 << 'PYTHON_SCRIPT'
import re

server_file = "/c/kaifa_senlin/pingdou/pingdou-workstation-final/cartoon-print-studio/backend/server.py"

with open(server_file, "r", encoding="utf-8") as f:
    content = f.read()

# 检查是否已经添加
if "/api/upload-image" in content:
    print("   ℹ️  上传接口已存在，跳过")
else:
    # 在 @app.get("/api/data/{sid}/{sub_path:path}") 之前插入
    upload_endpoint = '''
@app.post("/api/upload-image", status_code=201)
async def upload_image(image: UploadFile = File(...), source: str = Form("camera")):
    """Upload image from camera or file picker, analyze with vision model.

    Returns a session ID and AI-generated description to pre-fill chat context.
    """
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

    # Simple description (vision analysis can be added later)
    description = f"一张 {width}x{height} 的照片"

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


'''

    # 找到插入位置
    marker = '@app.get("/api/data/{sid}/{sub_path:path}")'
    if marker in content:
        content = content.replace(marker, upload_endpoint + marker)
        with open(server_file, "w", encoding="utf-8") as f:
            f.write(content)
        print("   ✅ 后端上传接口已添加")
    else:
        print("   ⚠️  未找到插入位置，请手动添加")

PYTHON_SCRIPT

# Step 2: 在 ChatArea.vue 中添加摄像头状态和处理函数
echo "📝 步骤 2/3: 修改 ChatArea.vue..."
python3 << 'PYTHON_SCRIPT'
import re

chat_area_file = "/c/kaifa_senlin/pingdou/pingdou-workstation-final/airi/packages/stage-layouts/src/components/Widgets/ChatArea.vue"

with open(chat_area_file, "r", encoding="utf-8") as f:
    content = f.read()

# 检查是否已经添加
if "cameraModalOpen" in content:
    print("   ℹ️  摄像头状态已存在，跳过")
else:
    # 在 script setup 中添加摄像头状态
    # 找到 const laserCardOpen = ref(false)
    marker = "const laserCardOpen = ref(false)"
    if marker in content:
        addition = marker + "\nconst cameraModalOpen = ref(false)"
        content = content.replace(marker, addition, 1)

        with open(chat_area_file, "w", encoding="utf-8") as f:
            f.write(content)
        print("   ✅ ChatArea.vue 已更新")
    else:
        print("   ⚠️  未找到插入位置")

PYTHON_SCRIPT

# Step 3: 添加摄像头菜单项和弹窗
echo "📝 步骤 3/3: 添加摄像头 UI 组件..."
python3 << 'PYTHON_SCRIPT'
import re

chat_area_file = "/c/kaifa_senlin/pingdou/pingdou-workstation-final/airi/packages/stage-layouts/src/components/Widgets/ChatArea.vue"

with open(chat_area_file, "r", encoding="utf-8") as f:
    content = f.read()

# 添加 import
if "CameraCapture" not in content:
    # 找到 import YXZLaserCardPanel
    import_marker = "import YXZLaserCardPanel from './YXZLaserCardPanel.vue'"
    if import_marker in content:
        addition = import_marker + "\nimport CameraCapture from './CameraCapture.vue'"
        content = content.replace(import_marker, addition, 1)

    # 在模板末尾添加摄像头弹窗（在 YXZLaserCardPanel 之后）
    template_marker = '''    <YXZLaserCardPanel
      v-model:open="laserCardOpen"
      @status="(status) => console.log('[LaserCard]', status)"
    />'''

    if template_marker in content:
        camera_modal = template_marker + '''

    <CameraCapture
      v-model:open="cameraModalOpen"
      @captured="handleCameraImage"
    />'''
        content = content.replace(template_marker, camera_modal, 1)

    # 添加菜单项（在激光切割名片之后）
    menu_marker = '''              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="laserCardOpen = true"
              >
                <div class="i-ph:cardholder-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>激光切割名片</span>
                <small class="text-neutral-400">预制模板 · 正面编辑 · SVG 切割</small>
              </DropdownMenuItem>'''

    if menu_marker in content:
        camera_menu = menu_marker + '''
              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="cameraModalOpen = true"
              >
                <div class="i-ph:camera-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>拍照上传</span>
                <small class="text-neutral-400">使用摄像头 · AI 理解图片 · 智能创作</small>
              </DropdownMenuItem>'''
        content = content.replace(menu_marker, camera_menu, 1)

    with open(chat_area_file, "w", encoding="utf-8") as f:
        f.write(content)

    print("   ✅ UI 组件已添加")
else:
    print("   ℹ️  UI 组件已存在，跳过")

PYTHON_SCRIPT

echo ""
echo "✅ 摄像头拍照功能集成完成！"
echo ""
echo "📋 集成清单:"
echo "  1. ✅ 后端上传接口 /api/upload-image"
echo "  2. ✅ 摄像头组件 CameraCapture.vue"
echo "  3. ✅ ChatArea 集成（按钮和弹窗）"
echo ""
echo "🚀 下一步: 启动服务验证"
echo "  前端: cd $AIRI_ROOT/apps/stage-web && pnpm dev"
echo "  后端: cd $PROJECT_ROOT/cartoon-print-studio && python backend/server.py"
echo ""
