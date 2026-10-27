#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜小智 VRM 模型自动优化脚本
使用 trimesh 和 pygltflib 进行模型压缩
"""
import os
import sys
import json
import shutil
from pathlib import Path

# 设置标准输出编码为 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def check_file_size(file_path):
    """检查文件大小"""
    if not file_path.exists():
        return 0
    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    return size_mb

def backup_original(vrm_path):
    """备份原始文件"""
    backup_path = vrm_path.with_suffix('.vrm.backup')
    if not backup_path.exists():
        shutil.copy2(vrm_path, backup_path)
        print(f"✅ 备份原文件: {backup_path.name}")
        return True
    else:
        print(f"ℹ️  备份已存在: {backup_path.name}")
        return False

def try_import_dependencies():
    """尝试导入依赖"""
    missing = []

    try:
        import trimesh
    except ImportError:
        missing.append('trimesh')

    try:
        from pygltflib import GLTF2
    except ImportError:
        missing.append('pygltflib')

    return missing

def install_dependencies(missing):
    """安装缺失的依赖"""
    if not missing:
        return True

    print(f"\n📦 需要安装依赖: {', '.join(missing)}")
    print("正在安装...")

    try:
        import subprocess
        for pkg in missing:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])
        print("✅ 依赖安装完成\n")
        return True
    except Exception as e:
        print(f"❌ 安装失败: {e}")
        return False

def optimize_with_trimesh(vrm_path):
    """使用 trimesh 优化模型"""
    try:
        import trimesh

        print("📊 加载模型...")
        mesh = trimesh.load(str(vrm_path), force='mesh')

        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
        else:
            meshes = [mesh]

        print(f"📐 当前模型统计:")
        total_faces = sum(m.faces.shape[0] for m in meshes if hasattr(m, 'faces'))
        total_vertices = sum(m.vertices.shape[0] for m in meshes if hasattr(m, 'vertices'))
        print(f"   - 面数: {total_faces:,}")
        print(f"   - 顶点数: {total_vertices:,}")

        # 简化网格
        print("\n🔧 简化网格 (保留 60% 面数)...")
        optimized_meshes = []
        for i, m in enumerate(meshes):
            if hasattr(m, 'simplify_quadric_decimation'):
                target_faces = int(m.faces.shape[0] * 0.6)
                simplified = m.simplify_quadric_decimation(target_faces)
                optimized_meshes.append(simplified)
                print(f"   - 网格 {i+1}: {m.faces.shape[0]:,} → {simplified.faces.shape[0]:,} 面")
            else:
                optimized_meshes.append(m)

        # 导出
        output_path = vrm_path.with_name('yxz-optimized.glb')
        print(f"\n💾 导出优化后的模型...")

        if len(optimized_meshes) == 1:
            optimized_meshes[0].export(str(output_path))
        else:
            scene = trimesh.Scene()
            for i, m in enumerate(optimized_meshes):
                scene.add_geometry(m, node_name=f'mesh_{i}')
            scene.export(str(output_path))

        return output_path

    except Exception as e:
        print(f"❌ Trimesh 优化失败: {e}")
        return None

def optimize_with_pygltflib(input_path, output_path):
    """使用 pygltflib 添加 Draco 压缩"""
    try:
        from pygltflib import GLTF2

        print(f"\n🗜️  应用 Draco 压缩...")
        gltf = GLTF2().load(str(input_path))

        # 注意：pygltflib 本身不支持 Draco 编码
        # 这里只是重新保存，实际压缩需要 gltfpack
        gltf.save(str(output_path))

        print(f"✅ 保存完成")
        return True

    except Exception as e:
        print(f"⚠️  Pygltflib 处理跳过: {e}")
        return False

def main():
    print("=" * 60)
    print("  宜小智 VRM 模型自动优化工具")
    print("=" * 60)
    print()

    # 定位模型文件
    vrm_path = Path("airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")

    if not vrm_path.exists():
        print(f"❌ 未找到模型文件: {vrm_path}")
        print("\n💡 提示: 请在项目根目录运行此脚本")
        return 1

    # 检查文件大小
    original_size = check_file_size(vrm_path)
    print(f"📦 原始模型: {vrm_path.name}")
    print(f"📏 文件大小: {original_size:.2f} MB")

    if original_size < 15:
        print(f"\n✅ 模型大小已经很合理 (< 15MB)")
        print("   无需优化")
        return 0

    print(f"⚠️  文件过大，建议优化到 < 12MB\n")

    # 备份
    backup_original(vrm_path)

    # 检查依赖
    missing = try_import_dependencies()
    if missing:
        print(f"\n⚠️  缺少 Python 依赖: {', '.join(missing)}")
        choice = input("是否自动安装? (y/n): ").strip().lower()
        if choice == 'y':
            if not install_dependencies(missing):
                print("\n❌ 依赖安装失败")
                print("💡 手动安装: pip install trimesh pygltflib")
                return 1
        else:
            print("\n💡 请手动安装: pip install trimesh pygltflib")
            return 1

    # 优化模型
    print("\n" + "=" * 60)
    print("开始优化模型...")
    print("=" * 60)

    optimized_path = optimize_with_trimesh(vrm_path)

    if not optimized_path or not optimized_path.exists():
        print("\n❌ 优化失败")
        print("\n💡 备选方案:")
        print("   1. 使用 Blender 手动优化 (见 MODEL-OPTIMIZATION-GUIDE.md)")
        print("   2. 下载 gltfpack 工具进行压缩")
        return 1

    # 检查优化效果
    optimized_size = check_file_size(optimized_path)
    reduction = (1 - optimized_size / original_size) * 100

    print("\n" + "=" * 60)
    print("优化完成！")
    print("=" * 60)
    print(f"原始大小: {original_size:.2f} MB")
    print(f"优化后:   {optimized_size:.2f} MB")
    print(f"减少:     {reduction:.1f}%")

    if optimized_size > 15:
        print(f"\n⚠️  优化后仍较大 ({optimized_size:.2f} MB)")
        print("💡 建议使用 gltfpack 进一步压缩:")
        print(f"   gltfpack -i {optimized_path.name} -o yxz-final.vrm -cc -tc")
    else:
        print(f"\n✅ 优化效果良好！")

    # 替换原文件
    print(f"\n是否替换原文件? (当前文件已备份为 {vrm_path.name}.backup)")
    choice = input("替换原文件? (y/n): ").strip().lower()

    if choice == 'y':
        vrm_path.unlink()
        shutil.move(str(optimized_path), str(vrm_path))
        print(f"\n✅ 已替换原文件")
        print(f"   新文件: {vrm_path.name} ({optimized_size:.2f} MB)")
        print(f"   备份: {vrm_path.name}.backup ({original_size:.2f} MB)")
    else:
        print(f"\n✅ 优化后的文件保存为: {optimized_path.name}")
        print(f"   如需使用，请手动替换:")
        print(f"   1. 删除 {vrm_path.name}")
        print(f"   2. 重命名 {optimized_path.name} 为 {vrm_path.name}")

    print("\n" + "=" * 60)
    print("✨ 优化完成！重启项目查看效果")
    print("=" * 60)

    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
