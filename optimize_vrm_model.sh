#!/bin/bash
# 🚀 VRM 模型优化脚本
# 将 yxz.vrm 从 11.7MB 压缩到 < 8MB

set -e

echo "========================================"
echo "🚀 宜小智 VRM 模型优化工具"
echo "========================================"
echo ""

MODEL_DIR="/c/kaifa_senlin/pingdou/pingdou-workstation-final/airi/packages/stage-ui-three/src/assets/vrm/models"
ORIGINAL_MODEL="$MODEL_DIR/yxz.vrm"
BACKUP_MODEL="$MODEL_DIR/yxz-original-backup.vrm"
OPTIMIZED_MODEL="$MODEL_DIR/yxz-optimized.vrm"

# 检查原始模型是否存在
if [ ! -f "$ORIGINAL_MODEL" ]; then
  echo "❌ 错误: 找不到原始模型 $ORIGINAL_MODEL"
  exit 1
fi

# 获取原始文件大小
ORIGINAL_SIZE=$(stat -f%z "$ORIGINAL_MODEL" 2>/dev/null || stat -c%s "$ORIGINAL_MODEL" 2>/dev/null)
ORIGINAL_MB=$(echo "scale=2; $ORIGINAL_SIZE / 1048576" | bc)
echo "📊 原始模型大小: ${ORIGINAL_MB} MB"
echo ""

# 备份原始模型
if [ ! -f "$BACKUP_MODEL" ]; then
  echo "💾 备份原始模型..."
  cp "$ORIGINAL_MODEL" "$BACKUP_MODEL"
  echo "✅ 已备份到: $BACKUP_MODEL"
else
  echo "✅ 备份已存在: $BACKUP_MODEL"
fi
echo ""

# 检查是否安装了 gltf-transform
echo "🔍 检查 gltf-transform 工具..."
if ! command -v gltf-transform &> /dev/null; then
  echo "⚠️  gltf-transform 未安装，正在安装..."
  npm install -g @gltf-transform/cli
fi

# 使用 gltf-transform 优化模型
echo "🔧 正在优化模型（Draco 压缩 + 纹理优化）..."
echo "⏳ 这可能需要 1-2 分钟，请耐心等待..."
echo ""

npx gltf-transform optimize \
  "$ORIGINAL_MODEL" \
  "$OPTIMIZED_MODEL" \
  --compress draco \
  --texture-compress webp \
  --quantize 16 \
  --prune-unused

if [ $? -eq 0 ]; then
  echo "✅ 优化完成！"
  echo ""

  # 获取优化后文件大小
  OPTIMIZED_SIZE=$(stat -f%z "$OPTIMIZED_MODEL" 2>/dev/null || stat -c%s "$OPTIMIZED_MODEL" 2>/dev/null)
  OPTIMIZED_MB=$(echo "scale=2; $OPTIMIZED_SIZE / 1048576" | bc)
  REDUCTION_PCT=$(echo "scale=1; 100 - ($OPTIMIZED_SIZE * 100 / $ORIGINAL_SIZE)" | bc)

  echo "📊 优化结果:"
  echo "   原始: ${ORIGINAL_MB} MB"
  echo "   优化后: ${OPTIMIZED_MB} MB"
  echo "   减少: ${REDUCTION_PCT}%"
  echo ""

  # 检查是否达到目标 (< 8MB)
  if (( $(echo "$OPTIMIZED_MB < 8.0" | bc -l) )); then
    echo "🎉 成功！优化后的模型 < 8MB，符合目标"

    # 询问是否替换原始文件
    echo ""
    read -p "是否用优化后的模型替换原始文件？(y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      mv "$OPTIMIZED_MODEL" "$ORIGINAL_MODEL"
      echo "✅ 已替换原始模型"
      echo "💾 原始文件已备份为: $BACKUP_MODEL"
    else
      echo "ℹ️  保留两个版本:"
      echo "   原始: $ORIGINAL_MODEL"
      echo "   优化: $OPTIMIZED_MODEL"
    fi
  else
    echo "⚠️  警告: 优化后的模型仍然 > 8MB"
    echo "建议: 使用 Blender 手动减少面数和纹理分辨率"
  fi
else
  echo "❌ 优化失败"
  exit 1
fi

echo ""
echo "========================================"
echo "✅ 优化完成！"
echo "========================================"
