#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜小智 VRM 模型自动优化脚本（非交互版本）
"""
import sys
import shutil
from pathlib import Path

# Windows 编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def main():
    print("=" * 60)
    print("  宜小智 VRM 模型优化工具")
    print("=" * 60)

    vrm_path = Path("airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")

    if not vrm_path.exists():
        print(f"错误: 未找到模型文件 {vrm_path}")
        return 1

    original_size = vrm_path.stat().st_size / (1024 * 1024)
    print(f"\n原始模型: {vrm_path.name}")
    print(f"文件大小: {original_size:.2f} MB")

    if original_size < 15:
        print(f"\n模型大小合理 (< 15MB)，无需优化")
        return 0

    # 备份
    backup_path = vrm_path.with_suffix('.vrm.backup')
    if not backup_path.exists():
        shutil.copy2(vrm_path, backup_path)
        print(f"已备份: {backup_path.name}")

    # 导入trimesh
    try:
        import trimesh
        print("\n正在加载模型...")
    except ImportError:
        print("错误: trimesh 未安装")
        return 1

    # 加载模型
    try:
        mesh = trimesh.load(str(vrm_path), force='mesh')
    except Exception as e:
        print(f"错误: 无法加载模型 - {e}")
        return 1

    # 获取网格列表
    if isinstance(mesh, trimesh.Scene):
        meshes = list(mesh.geometry.values())
    else:
        meshes = [mesh]

    # 统计信息
    total_faces = sum(m.faces.shape[0] for m in meshes if hasattr(m, 'faces'))
    total_vertices = sum(m.vertices.shape[0] for m in meshes if hasattr(m, 'vertices'))
    print(f"\n当前统计:")
    print(f"  面数: {total_faces:,}")
    print(f"  顶点数: {total_vertices:,}")

    # 简化网格
    print(f"\n开始优化 (目标: 保留 60% 面数)...")
    optimized_meshes = []

    for i, m in enumerate(meshes):
        if hasattr(m, 'simplify_quadric_decimation') and hasattr(m, 'faces'):
            try:
                target_faces = max(100, int(m.faces.shape[0] * 0.6))
                simplified = m.simplify_quadric_decimation(target_faces)
                optimized_meshes.append(simplified)
                print(f"  网格 {i+1}: {m.faces.shape[0]:,} -> {simplified.faces.shape[0]:,} 面")
            except Exception as e:
                print(f"  网格 {i+1}: 简化失败，保留原始 - {e}")
                optimized_meshes.append(m)
        else:
            optimized_meshes.append(m)

    # 导出
    output_path = vrm_path.with_name('yxz-optimized.glb')
    print(f"\n导出优化后的模型...")

    try:
        if len(optimized_meshes) == 1:
            optimized_meshes[0].export(str(output_path))
        else:
            scene = trimesh.Scene()
            for idx, m in enumerate(optimized_meshes):
                scene.add_geometry(m, node_name=f'mesh_{idx}')
            scene.export(str(output_path), file_type='glb')
    except Exception as e:
        print(f"错误: 导出失败 - {e}")
        return 1

    # 检查结果
    if not output_path.exists():
        print("错误: 优化后的文件未生成")
        return 1

    optimized_size = output_path.stat().st_size / (1024 * 1024)
    reduction = (1 - optimized_size / original_size) * 100

    print(f"\n" + "=" * 60)
    print("优化完成!")
    print("=" * 60)
    print(f"原始大小: {original_size:.2f} MB")
    print(f"优化后:   {optimized_size:.2f} MB")
    print(f"减少:     {reduction:.1f}%")

    # 自动替换
    print(f"\n正在替换原文件...")
    vrm_path.unlink()
    shutil.move(str(output_path), str(vrm_path))

    print(f"\n完成!")
    print(f"  新文件: {vrm_path.name} ({optimized_size:.2f} MB)")
    print(f"  备份: {backup_path.name} ({original_size:.2f} MB)")

    if optimized_size > 15:
        print(f"\n提示: 优化后仍较大，建议使用 gltfpack 进一步压缩")

    print("\n" + "=" * 60)
    print("重启项目查看效果: START.bat")
    print("=" * 60)

    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n用户取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
