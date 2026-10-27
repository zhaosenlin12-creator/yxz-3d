#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VRM 模型转换和优化工具
VRM 本质上是 GLB 格式 + VRM 扩展
"""
import sys
import shutil
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def main():
    print("=" * 60)
    print("  VRM 模型优化工具")
    print("=" * 60)

    vrm_path = Path("airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")

    if not vrm_path.exists():
        print(f"错误: 未找到 {vrm_path}")
        return 1

    original_size = vrm_path.stat().st_size / (1024 * 1024)
    print(f"\n原始文件: {vrm_path.name}")
    print(f"大小: {original_size:.2f} MB")

    # 备份
    backup_path = vrm_path.with_suffix('.vrm.backup')
    if not backup_path.exists():
        shutil.copy2(vrm_path, backup_path)
        print(f"已备份: {backup_path.name}")

    # VRM 实际上就是 GLB，尝试作为 GLB 加载
    print("\n正在处理...")

    try:
        import trimesh
        # 强制作为 glb 加载
        glb_temp = vrm_path.with_suffix('.glb')
        shutil.copy2(vrm_path, glb_temp)

        print("加载模型 (作为 GLB)...")
        mesh = trimesh.load(str(glb_temp), file_type='glb', force='mesh')

        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
            print(f"找到 {len(meshes)} 个网格对象")
        else:
            meshes = [mesh]

        # 统计
        total_faces = sum(m.faces.shape[0] for m in meshes if hasattr(m, 'faces'))
        total_verts = sum(m.vertices.shape[0] for m in meshes if hasattr(m, 'vertices'))

        print(f"\n原始统计:")
        print(f"  面数: {total_faces:,}")
        print(f"  顶点: {total_verts:,}")

        # 简化
        print(f"\n开始简化 (保留 65% 面数)...")
        optimized = []

        for i, m in enumerate(meshes):
            if hasattr(m, 'simplify_quadric_decimation') and hasattr(m, 'faces'):
                original_count = m.faces.shape[0]
                if original_count < 500:
                    print(f"  网格{i+1}: 面数过少 ({original_count}), 跳过")
                    optimized.append(m)
                    continue

                try:
                    target = max(300, int(original_count * 0.65))
                    result = m.simplify_quadric_decimation(target)
                    optimized.append(result)
                    print(f"  网格{i+1}: {original_count:,} -> {result.faces.shape[0]:,} 面 ({result.faces.shape[0]*100/original_count:.1f}%)")
                except Exception as e:
                    print(f"  网格{i+1}: 简化失败，保留原始")
                    optimized.append(m)
            else:
                optimized.append(m)

        # 导出
        output_glb = vrm_path.parent / 'yxz-optimized.glb'
        print(f"\n导出到: {output_glb.name}")

        if len(optimized) == 1:
            optimized[0].export(str(output_glb), file_type='glb')
        else:
            scene = trimesh.Scene()
            for idx, m in enumerate(optimized):
                scene.add_geometry(m, node_name=f'mesh_{idx}')
            scene.export(str(output_glb), file_type='glb')

        # 清理临时文件
        glb_temp.unlink()

        if not output_glb.exists():
            print("错误: 导出失败")
            return 1

        optimized_size = output_glb.stat().st_size / (1024 * 1024)
        reduction = (1 - optimized_size / original_size) * 100

        print(f"\n" + "=" * 60)
        print(f"原始: {original_size:.2f} MB")
        print(f"优化: {optimized_size:.2f} MB")
        print(f"减少: {reduction:.1f}%")
        print("=" * 60)

        # 重命名为 VRM（因为 VRM 就是 GLB）
        output_vrm = output_glb.with_suffix('.vrm')
        if output_vrm.exists():
            output_vrm.unlink()
        output_glb.rename(output_vrm)

        # 替换原文件
        vrm_path.unlink()
        shutil.move(str(output_vrm), str(vrm_path))

        final_size = vrm_path.stat().st_size / (1024 * 1024)
        print(f"\n完成! 新文件: {vrm_path.name} ({final_size:.2f} MB)")
        print(f"备份: {backup_path.name}")

        if final_size < 15:
            print("\n成功! 文件大小已优化到合理范围")
        else:
            print(f"\n提示: 文件仍有 {final_size:.2f} MB")
            print("建议下载 gltfpack 进一步压缩纹理")

        return 0

    except ImportError:
        print("\n错误: trimesh 未安装")
        print("运行: pip install trimesh")
        return 1
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
