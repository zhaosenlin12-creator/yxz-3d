#!/bin/bash
# 快速验收测试脚本

cd /c/kaifa_senlin/pingdou/pingdou-workstation-final

echo "🧪 开始验收测试..."
echo "================================"

# 1. 检查服务运行
echo ""
echo "1️⃣ 检查服务状态..."
echo "----------------------------"

if curl -s http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    echo "✅ 后端运行中 (http://127.0.0.1:8000)"
else
    echo "❌ 后端未运行"
fi

FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5199 2>/dev/null || echo "000")
if [ "$FRONTEND_STATUS" = "200" ]; then
    echo "✅ 前端运行中 (http://localhost:5199)"
else
    echo "⚠️  前端状态: $FRONTEND_STATUS (可能仍在编译)"
fi

# 2. 测试激光卡片 API
echo ""
echo "2️⃣ 测试激光卡片 API..."
echo "----------------------------"

LASER_RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/api/laser/card \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "acceptance_test",
    "name": "张三",
    "title": "产品经理",
    "unit": "XX科技",
    "contact": "手机: 138-1234-5678",
    "slogan": "创新驱动",
    "theme": "#0B5FA8"
  }' 2>/dev/null)

if echo "$LASER_RESPONSE" | grep -q "svg_path"; then
    echo "✅ 激光卡片 API 正常"
    echo "   生成的文件:"

    # 提取 session_id
    SESSION_ID=$(echo "$LASER_RESPONSE" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
    if [ -n "$SESSION_ID" ]; then
        LASER_DIR="cartoon-print-studio/data/laser/$SESSION_ID"
        if [ -d "$LASER_DIR" ]; then
            ls -lh "$LASER_DIR" | tail -n +2 | while read -r line; do
                echo "   $(echo "$line" | awk '{print "  -", $9, "("$5")"}')"
            done
        fi
    fi
else
    echo "❌ 激光卡片 API 失败"
    echo "   响应: $LASER_RESPONSE"
fi

# 3. 测试软件检测 API
echo ""
echo "3️⃣ 测试软件检测 API..."
echo "----------------------------"

SOFTWARE_RESPONSE=$(curl -s http://127.0.0.1:8000/api/software/detect 2>/dev/null)

if echo "$SOFTWARE_RESPONSE" | grep -q "xtool_studio"; then
    echo "✅ 软件检测 API 正常"
    echo "   检测结果:"
    echo "$SOFTWARE_RESPONSE" | python -m json.tool 2>/dev/null | grep -E "bambu_studio|xtool_studio" | while read -r line; do
        echo "     $line"
    done
else
    echo "❌ 软件检测 API 失败"
fi

# 4. 检查 VRM 模型文件
echo ""
echo "4️⃣ 检查 VRM 模型大小..."
echo "----------------------------"

VRM_FILE="airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"
if [ -f "$VRM_FILE" ]; then
    VRM_SIZE=$(stat -c%s "$VRM_FILE" 2>/dev/null || stat -f%z "$VRM_FILE" 2>/dev/null)
    VRM_MB=$((VRM_SIZE / 1024 / 1024))

    if [ $VRM_SIZE -gt 8388608 ]; then
        echo "⚠️  VRM 模型: ${VRM_MB}MB (建议压缩到 < 8MB)"
    else
        echo "✅ VRM 模型: ${VRM_MB}MB (大小合适)"
    fi
else
    echo "❌ VRM 模型文件不存在"
fi

# 5. 检查组件大小
echo ""
echo "5️⃣ 检查巨型组件..."
echo "----------------------------"

SCENE_FILE="airi/packages/stage-ui-three/src/components/YXZRealModelScene.vue"
if [ -f "$SCENE_FILE" ]; then
    LINE_COUNT=$(wc -l < "$SCENE_FILE")
    echo "📄 YXZRealModelScene.vue: $LINE_COUNT 行"

    if [ $LINE_COUNT -gt 3000 ]; then
        echo "⚠️  组件过大，建议拆分"
    else
        echo "✅ 组件大小合理"
    fi
else
    echo "❌ YXZRealModelScene.vue 不存在"
fi

# 6. 检查加载进度组件
echo ""
echo "6️⃣ 检查加载进度组件..."
echo "----------------------------"

PROGRESS_COMPONENT="airi/apps/stage-web/src/components/YXZLoadingProgress.vue"
if [ -f "$PROGRESS_COMPONENT" ]; then
    echo "✅ YXZLoadingProgress.vue 已创建"

    # 检查是否已集成
    PREVIEW_PAGE="airi/apps/stage-web/src/pages/yxz-vrm-preview.vue"
    if grep -q "YXZLoadingProgress" "$PREVIEW_PAGE" 2>/dev/null; then
        echo "✅ 已集成到预览页面"
    else
        echo "⏳ 待集成到预览页面"
    fi
else
    echo "❌ YXZLoadingProgress.vue 未创建"
fi

# 7. 测试 API 端点
echo ""
echo "7️⃣ 测试其他 API 端点..."
echo "----------------------------"

# 测试健康检查
HEALTH=$(curl -s http://127.0.0.1:8000/api/health 2>/dev/null)
if echo "$HEALTH" | grep -q "status"; then
    echo "✅ /api/health - 正常"
else
    echo "❌ /api/health - 失败"
fi

# 测试模板列表
TEMPLATES=$(curl -s http://127.0.0.1:8000/api/laser/templates 2>/dev/null)
if echo "$TEMPLATES" | grep -q "id\|name"; then
    TEMPLATE_COUNT=$(echo "$TEMPLATES" | grep -o "\"id\"" | wc -l)
    echo "✅ /api/laser/templates - 正常 ($TEMPLATE_COUNT 个模板)"
else
    echo "⚠️  /api/laser/templates - 无模板或失败"
fi

# 8. 总结
echo ""
echo "================================"
echo "🎉 验收测试完成！"
echo "================================"
echo ""
echo "📊 测试摘要:"
echo "  ✅ 后端运行: $([ $(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null) = "200" ] && echo "是" || echo "否")"
echo "  ✅ 前端运行: $([ "$FRONTEND_STATUS" = "200" ] && echo "是" || echo "编译中")"
echo "  ✅ 激光卡片: $(echo "$LASER_RESPONSE" | grep -q "svg_path" && echo "正常" || echo "需检查")"
echo "  ⚠️  VRM 模型: ${VRM_MB}MB (目标 < 8MB)"
echo "  ⚠️  巨型组件: $LINE_COUNT 行 (目标 < 3000)"
echo ""
echo "📝 详细报告:"
echo "  - ACCEPTANCE_TEST.md - 完整验收清单"
echo "  - PERFORMANCE_REPORT.md - 性能分析"
echo "  - OPTIMIZATION_PLAN.md - 优化计划"
echo ""
echo "🚀 下一步:"
echo "  1. 打开浏览器测试: http://localhost:5199"
echo "  2. 测试激光卡片功能"
echo "  3. 测试语音输入"
echo "  4. 等待其他智能体完成 3D 动态效果"
echo ""
