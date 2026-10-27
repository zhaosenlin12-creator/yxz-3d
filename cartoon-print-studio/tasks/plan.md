# Implementation Plan: 单机 AI 3D 创作与打印体验

## Overview

让学生在单机环境里快速感受到“描述 → 2D 预览 → 高质量 3D → 编辑 → 导出/打印”的完整 AI 创作闭环。

## Architecture Decisions

- 保留现有 FastAPI + Python 推理链路；本地优先使用 Hunyuan3D-2 mini，TripoSR 与卡通浮雕作为免费 fallback，Tripo3D 仅作为可选云端贴图通道。
- 前端继续使用现有 Three.js，先补齐快速体验、质量选择和打印交付信息；后续再迁移 React/R3F。
- 快速体验使用仓库内已经存在的示例 GLB，避免学生第一次进入就等待云端任务。
- 真实项目仍以 session_id 为主键，导出沿用 `/api/export/{sid}/{fmt}`，打印沿用 `/api/print`。

## Task List

### Phase 1: 快速体验
- [x] 首页增加“立即体验示例模型”入口，加载本地示例 GLB 并进入 3D 工作台。
- [x] 展示体验说明，让学生知道下一步可以编辑、保存、导出。

### Phase 2: 高质量生成与交付
- [x] 3D 步骤增加质量/速度说明和推荐默认项。
- [x] 增加清晰的 STL、OBJ、GLB 导出按钮，减少 prompt 选择。
- [x] 增加打印准备状态、Bambu Studio 快捷操作说明和失败 fallback 提示。

### Phase 3: 3D 预览与结构查看
- [x] Three.js 拖动旋转、滚轮缩放和重置视角。
- [x] 增加半透明查看模式。
- [x] 增加拆解视图控件；多节点 GLB 可按零件散开，单一网格给出明确提示。
- [ ] 后端语义分件/零件 GLB 导出，让任意 AI 模型都能稳定拆解。

### Phase 4: 开源建模引擎优化
- [x] 接入 Hunyuan3D-2 mini 本地高质图生 3D，并设为有 GPU 时的默认引擎。
- [x] 保留 TripoSR 多视角与卡通浮雕，形成免费、可离线的降级链路。
- [x] 增加 `/api/engines`，启动后按 GPU、权重和 API key 自动标记引擎可用性。
- [x] 在 GTX 1060 6GB 上验证平衡档：6 steps / octree 112，成功导出 GLB、OBJ、STL。
- [ ] 在更高显存机器上评估 Stable Fast 3D / Hunyuan3D-2.1，再决定是否加入安装包。

### Phase 5: 专业创作体验
- [x] 蓝色专业工作台视觉、统一 SVG 图标、减少装饰性 emoji。
- [x] 用扫描线、网格、形体/细节/网格阶段提示替换纯 loading spinner，展示模型逐步成型。
- [x] 扩展可编辑素材：球体、方块、圆锥、圆柱、圆环、水晶、胶囊、爱心。
- [x] 新增独立“真实场景 / Gaussian Splat”浏览器体验模式，不与 STL/打印流程混合。
- [ ] 接入 GraphDECO / gsplat 的服务端多视角训练与 `.ply` / `.splat` 成果加载；单张图只能生成视差体验，不能替代真实多视角重建。

### Checkpoint: Core Flow
- [x] 页面/健康检查通过。
- [x] 示例模型能够进入工作台。
- [x] 真实生成接口 payload 保持兼容。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 云端生成耗时较长 | 学生首次体验中断 | 先进入本地示例体验，再启动 AI 生成 |
| Tripo3D 额度/网络异常 | 无法得到高质量模型 | 保留现有卡通浮雕与 TripoSR fallback |
| 导出格式选择困难 | 学生无法顺利打印 | 直接提供 STL（打印）、OBJ（编辑）、GLB（贴图）按钮 |
