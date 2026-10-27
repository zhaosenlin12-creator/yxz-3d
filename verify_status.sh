#!/bin/bash
# 宜小智工作台 - 实时验证脚本
# 运行前提：服务已启动在 localhost:5199 和 localhost:8000

echo "=========================================="
echo "宜小智工作台 - 实时验证开始"
echo "=========================================="
echo ""

# 检查服务是否运行
echo "1. 检查服务状态..."
echo "   - 前端服务 (5199):"
if curl -s http://localhost:5199 > /dev/null 2>&1; then
    echo "     ✅ 前端服务运行正常"
else
    echo "     ❌ 前端服务未运行（请先启动: cd airi/apps/stage-web && pnpm dev）"
fi

echo "   - 后端服务 (8000):"
if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo "     ✅ 后端服务运行正常"
else
    echo "     ❌ 后端服务未运行（请先启动: cd cartoon-print-studio && python backend/server.py）"
fi

echo ""
echo "2. 检查 3D 模型文件..."
cd /c/kaifa_senlin/pingdou/pingdou-workstation-final
VRM_FILE="airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"
if [ -f "$VRM_FILE" ]; then
    SIZE=$(du -h "$VRM_FILE" | cut -f1)
    echo "   ✅ VRM 模型存在: $SIZE"
    if [ "$(stat -c%s "$VRM_FILE")" -gt 20000000 ]; then
        echo "   ⚠️  警告: 文件大于 20MB，建议压缩"
    fi
else
    echo "   ❌ VRM 模型文件不存在"
fi

echo ""
echo "3. 检查激光切割组件是否集成..."
LASER_COMPONENT="airi/packages/stage-ui/src/components/scenes/YXZLaserCardPanel.vue"
if [ -f "$LASER_COMPONENT" ]; then
    echo "   ✅ YXZLaserCardPanel 组件存在"

    # 检查是否在主页面中导入
    if grep -r "YXZLaserCardPanel" airi/apps/stage-web/src/pages/*.vue > /dev/null 2>&1; then
        echo "   ✅ 组件已集成到页面"
    else
        echo "   ❌ 组件未集成到页面（需要导入）"
    fi
else
    echo "   ❌ YXZLaserCardPanel 组件不存在"
fi

echo ""
echo "4. 检查后端 API 可用性..."
echo "   - 激光卡片 API:"
if curl -s http://localhost:8000/api/laser/templates > /dev/null 2>&1; then
    echo "     ✅ /api/laser/templates 正常"
else
    echo "     ❌ /api/laser/templates 不可用"
fi

echo "   - 3D 生成 API:"
if curl -s -X OPTIONS http://localhost:8000/api/3d_tripo > /dev/null 2>&1; then
    echo "     ✅ /api/3d_tripo 存在"
else
    echo "     ⚠️  /api/3d_tripo 检查失败（可能需要 POST 请求）"
fi

echo ""
echo "5. 检查最近的 3D 生成结果..."
DATA_DIR="cartoon-print-studio/data"
if [ -d "$DATA_DIR" ]; then
    RECENT_MODEL=$(find "$DATA_DIR" -name "mesh.glb" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
    if [ -n "$RECENT_MODEL" ]; then
        SIZE=$(du -h "$RECENT_MODEL" | cut -f1)
        echo "   ✅ 找到最近的模型: $RECENT_MODEL ($SIZE)"

        # 检查文件是否过小（可能是空文件或立方体）
        BYTES=$(stat -c%s "$RECENT_MODEL" 2>/dev/null)
        if [ "$BYTES" -lt 10000 ]; then
            echo "   ⚠️  警告: 模型文件小于 10KB，可能不是真实 3D 模型"
        elif [ "$BYTES" -lt 100000 ]; then
            echo "   ⚠️  注意: 模型文件小于 100KB，可能是简化的 2.5D 浮雕"
        else
            echo "   ✅ 模型文件大小正常（> 100KB），可能是真实 3D 模型"
        fi
    else
        echo "   ⏸️  未找到生成的模型文件"
    fi
else
    echo "   ❌ 数据目录不存在"
fi

echo ""
echo "6. 检查语音输入组件..."
SPEECH_FILES=$(grep -r "useSpeechRecognition\|SpeechRecognition" airi/packages/stage-ui/src/composables/*.ts 2>/dev/null | wc -l)
if [ "$SPEECH_FILES" -gt 0 ]; then
    echo "   ✅ 找到语音识别相关代码 ($SPEECH_FILES 处)"
else
    echo "   ❌ 未找到语音识别相关代码"
fi

echo ""
echo "=========================================="
echo "验证完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 如果服务未运行，请先启动前后端服务"
echo "2. 打开浏览器访问 http://localhost:5199"
echo "3. 手动验证以下功能："
echo "   - 在对话中输入'制作激光切割卡片'"
echo "   - 点击麦克风图标测试语音输入"
echo "   - 生成 3D 模型并查看是否是真实 3D"
echo "   - 访问 /yxz-vrm-preview 查看宜小智动作"
echo ""
echo "详细待办事项见: TODO_VERIFICATION.md"
