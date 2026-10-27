# VRM 模型优化指南（必须执行）

> ⚠️ **当前状态**：yxz.vrm 文件 **36MB**，导致首屏加载 20-35 秒
> 🎯 **优化目标**：压缩到 **8-12MB**，加载时间降至 6-10 秒

---

## 方案 A：使用 Blender（推荐）

### 1. 下载 Blender
https://www.blender.org/download/

### 2. 导入模型
File → Import → glTF 2.0 → 选择 yxz.vrm

### 3. 简化网格
- 选择网格对象
- Add Modifier → Decimate
- Ratio: 0.6
- Apply

### 4. 导出
File → Export → glTF 2.0
- Format: GLB
- Compression: Draco (Level 6)
- 保存为: yxz-optimized.glb

### 5. 替换
```bash
cd airi/packages/stage-ui-three/src/assets/vrm/models
mv yxz.vrm yxz.vrm.old
mv yxz-optimized.glb yxz.vrm
```

---

## 方案 B：使用 gltfpack

下载：https://github.com/zeux/meshoptimizer/releases

```bash
cd airi/packages/stage-ui-three/src/assets/vrm/models
gltfpack -i yxz.vrm -o yxz-optimized.vrm -cc -tc
mv yxz.vrm yxz.vrm.old
mv yxz-optimized.vrm yxz.vrm
```

---

## 验证

```bash
cd /c/kaifa_senlin/pingdou/pingdou-workstation-final
START.bat
```

打开 http://localhost:5199/yxz-vrm-preview

- ✅ 加载时间 < 10 秒
- ✅ 模型正常显示
- ✅ 有加载进度条

**预计时间**：30-45 分钟
