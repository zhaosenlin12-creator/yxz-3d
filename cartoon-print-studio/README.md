# Cartoon Print Studio · 卡通 3D 打印工坊

> AI 生成卡通造型 → 选图 → Tripo3D 真 3D 建模 → Bambu Studio 一键打印。
> 适合 3D 打印门店现场给顾客定制小摆件。

## 特性

- **AI 思考链** — MiniMax(.com)/DeepSeek 大模型拆需求 → aixj gpt-image / minimax / jojo / 本地 SD 自动出 4 张不同姿势/视角的预览
- **Hunyuan3D-2 mini 本地高质** — 默认本地引擎，不消耗 Tripo3D 额度；首次加载模型较慢，后续在 6GB 显存档位生成可打印网格
- **TripoSR 多视角本地** — 更快的开源草模路径，适合课堂试错
- **Tripo3D 真 3D** — 云端 v3.1 模型带 PBR 贴图，约 2-3 分钟出 1 个模型（保留为可选高质贴图通道）
- **自动 fallback** — Hunyuan/Tripo 失败、余额低或网络抖动 → 自动落到 TripoSR 多视角 / 卡通浮雕，离线也能用
- **稳定性** — polling SSL 容错 + multi-key 轮换 + jojo 余额熔断 + task_id 持久化
- **Bambu Studio 自动检测** — 注册表 / Program Files / WindowsApps / PATH 全扫一遍
- **一键打印** — 直接打开 STL 进 Bambu Studio
- **离线导出** — STL / OBJ / GLB 三种格式，没有打印机也能用
- **3D 工作台（新增）** — 在生成模型后添加圆球/方块/圆锥，选中后调整位置、大小、颜色，支持删除、复制、撤销
- **真实场景模式** — 独立的多视角真实场景链路：上传照片/视频、保存采集任务、提交 GPU worker，并在浏览器中用 SuperSplat 沉浸式查看 `.ply` / `.splat` / `.sog` / `.spz`，不进入打印流程
- **沉浸式模型查看** — 导出文件统一 Z-up、浏览器显示自动转为 Y-up，打印底板不会再变成竖直背景板；GLB 保留断开的部件节点，可用“拆开看”查看主体与底座。
- **本地作品库（新增）** — 保存作品名称、当前模型引用和场景素材，刷新页面后可继续编辑
- **零等待体验（新增）** — 首页可直接打开本机示例 GLB，不消耗 API 额度，先体验编辑/导出/打印再开始 AI 生成
- **打印交付（新增）** — 3D 页面直接下载 STL、OBJ、GLB，并显示 Bambu Studio 检测状态

### 创作工作台（对话 + 无限画布）

- **对话式创作** — 左侧对话栏显示你的描述、AI 阶段进度、预览集合、模型版本和错误重试；右侧无限画布摆素材，中间 3D 视窗。
- **画布即建模输入** — 画布上的预览图、导入图、便签和笔迹可合成一张最终 PNG，**这张图**才是送进建模引擎的输入；交付面板会明确显示即将使用的那张图。
- **版本不覆盖** — 每次生成产生新版本，旧版本保留，可随时切回继续编辑；版本记录来源会话、提示词、引擎和时间。
- **项目自动保存** — 项目 JSON 落在 `data/projects/`，聊天、画布布局、模型版本一起存；本机自动保存 + 手动保存 + 作品库入口。
- **语音输入** — 聊天框的“语音”按钮用浏览器 `SpeechRecognition`（普通话），实时回填临时文本，停止后文字留在输入框由你决定是否发送，**不会自动提交**。
- **提示词润色** — “润色”按钮给出预览对比，应用或撤销都需要确认；没有密钥或云端失败时退回本机规则建议，绝不静默替换原文。
- **3D 编辑进入导出** — 在 3D 视窗里加的球体/方块/圆锥会连同基础模型一起写进 STL / OBJ / GLB，不是只在前端看得见。

### 桌面软件交付边界

- **Bambu Studio** — 交付前先跑一遍打印预检（面数、封闭性、体积、尺寸），确认后打开当前版本的 STL。**只负责打开文件，不自动切片、不自动开始打印。**
- **xTool Studio** — 默认交付画布导出的 2D **PNG**，同时提供 SVG。**当前 SVG 是把位图包进矢量容器，不是真正的矢量轮廓**，用于激光切割前请在 xTool 里确认路径；未确认设备支持 3D 导入前，不开放 STL/OBJ/GLB 给 xTool。
- **路径可修正** — 交付面板可以查看每个软件的检测路径，手动填入 `.exe` 完整路径保存；填错时能一键“恢复自动检测”。修改保存在 `data/software_paths.json`，重启后仍然有效。
- **不自动加工** — 应用只把文件交给桌面软件，切片、参数和“开始打印/开始切割”都由你在软件里确认。

## 面向学生的产品升级路线

这个项目最适合做成“AI 3D 创作工作台”，而不是一开始就做成完整的游戏引擎。推荐把体验拆成三层：

1. **创意层**：一句话描述 → 2D 预览卡片 → 学生选择一个方案，并能重新生成或修改提示词。
2. **模型层**：选中的 2D → Tripo3D / Hunyuan3D / TripoSR → GLB 预览，显示面数、尺寸和生成耗时。
3. **世界层**：在模型上继续添加卡通素材、调整位置/颜色/大小、保存作品；后续再增加多人协作、课堂分享和打印队列。

### 推荐技术栈

- **前端**：React + TypeScript + Vite；3D 使用 Three.js / React Three Fiber，交互控件可用 drei，复杂场景状态用 Zustand。
- **后端**：保留当前 FastAPI + Python 推理服务；用 Redis/Celery（或现有 polling 先过渡）承载长耗时任务。
- **模型格式**：编辑态统一 GLB/glTF，打印前导出 STL；用 Draco/Meshopt 做传输压缩。
- **存储**：开发阶段 localStorage；上线课堂版用 SQLite/PostgreSQL + 对象存储（MinIO/S3）保存项目 JSON、预览图和模型文件。
- **体验质量**：编辑器使用固定卡通材质、灯光和色板；所有长任务都有阶段进度、可取消、失败回退和可恢复的任务 ID。

当前新增的 3D 工作台先复用现有原生 Three.js，避免一次性引入构建系统；等“素材库、课堂协作、多人场景”确定后，再平滑迁移到 React Three Fiber，不影响现有 FastAPI 接口。

### 真实场景模式的技术边界

真实 3D Gaussian Splat 需要多张照片或视频来估计相机位姿，再训练出 `.ply` / `.splat` 场景。当前项目已经把这条链路拆成可运行的三段：本地保存采集素材与质量评估、可配置的 GPU worker 提交契约、浏览器 SuperSplat 查看器。没有配置 worker 时，界面会保留任务并明确提示，不会伪造一个“看起来像真实场景”的结果。

GPU worker 可以用 [GraphDECO 3DGS](https://github.com/graphdeco-inria/gaussian-splatting)、[Nerfstudio / gsplat](https://github.com/nerfstudio-project/gsplat) 或兼容实现；训练完成后调用场景成果接口导入文件，再由官方 [PlayCanvas SuperSplat Viewer](https://github.com/playcanvas/supersplat-viewer) 在本地 WebGL 页面中加载。查看器支持轨道旋转、平移、缩放、第一人称漫游、光影和相机动画，场景模式与可打印网格模式相互独立。

### 本地真实场景测试（Windows）

开发环境已配置离线优先的 Brush + COLMAP 链路：`tools/brush` 和 `tools/colmap` 放在项目内，启动脚本会自动设置路径和 `SCENE_TRAINER_MODE=local`。它不依赖 Tripo 额度；训练完成后直接导出 PLY，并用本地 SuperSplat 预览。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1
Invoke-RestMethod http://127.0.0.1:8000/api/scenes/config
# 已有场景可检查：
powershell -ExecutionPolicy Bypass -File scripts\test_local_scene.ps1 -SceneId scene_xxxxxxxxxxxx
```

本地训练会先用 ffmpeg 从视频抽帧，再用 COLMAP 恢复相机轨迹。系统默认要求至少恢复 8 个有效视角；不足时会标记为失败并提示重新拍摄，不会把放射线、空场景误报为高质量结果。建议使用 10–30 秒、缓慢环绕主体拍摄的视频，或 20–60 张有明显视角变化的照片。

## API 优先级链

```
预览：aixj-image (gpt-image-2) → minimax-image → jojo-image (熔断) → 本地 SD
3D：  Tripo3D cloud v3.1     →  TripoSR (本地)     →  卡通浮雕 (本地)
```

## 快速开始

### 1. 配置 API 密钥

把 `C:\Users\<you>\Desktop\key.txt` 或安装目录（与 `CartoonPrintStudio.exe` 同级）下的 `keys.txt` 改成：

```
# LLM（对话思考 / 提示词润色）
minimax-key: sk-cp-...        # 主用（注意走 api.minimaxi.com 域名）
deepseek-key: sk-...          # 备用
# 生图（aixj 首选，minimax 备用）
aixj-image-key: sk-e1b84b...  # gpt-image-2，需浏览器 UA 才能下载图片
minimax-image-key: sk-cp-...
jojo-image-key: sk-...        # 兜底（jojo 余额不够自动跳过）
# 3D
TRIPO:3D模型生成
tsk_...                       # Tripo3D OpenAPI
```

查找顺序：`<安装目录>/keys.txt` → `~\Desktop\key.txt` → 环境变量。key 按行标签自动归类，deepseek / aixj / jojo 的 key 不会误发给其他服务。
没有可用密钥时应用仍可启动，工作台顶部会提示哪些能力不可用（云端预览、提示词润色、Tripo3D），本机卡通浮雕和卡通 3D 不受影响。

### 2. 装 Bambu Studio

<https://bambulab.com/en/download/studio> 装到默认位置，应用自动识别。

### 3. 启动

- **开发模式**: 双击 `start.bat`（浏览器自动开）
- **打包后**: 双击桌面 `Cartoon Print Studio` 快捷方式（PyWebView 弹原生窗口）
- 浏览器访问 <http://127.0.0.1:8000>

换端口或等待服务就绪：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1 -Port 8010 -Wait
powershell -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
```

启动脚本会自己处理三种常见情况：残留 PID 文件会清理、端口被占用会明确告诉你（如果占用者就是本应用则直接复用）、缺虚拟环境时回退到系统 Python。

## 数据保存位置

所有本机数据都在项目/安装目录下，不进 Git：

| 位置 | 内容 |
|---|---|
| `data/projects/` | 项目 JSON：对话、提示词、画布元素、模型版本、引用关系 |
| `data/projects/media/` | 项目引用的上传图片 |
| `data/<sessionId>/` | 每个会话的预览图、模型、导出文件 |
| `data/software_paths.json` | 手动修正过的桌面软件路径 |
| `logs/` | 后端日志、浏览器回归截图、构建日志 |

项目 JSON 采用原子写入（先写临时文件再替换），保存前校验 schema、项目 ID、消息长度和画布坐标；引用的文件缺失时不会静默失败，而是在载入时列出 `missingReferences` 提示你重新选择素材。

旧版本存在 localStorage 里的作品会在**首次启动时一次性导入**到 `data/projects/`，导入后仍保留原来的 localStorage 数据，不会被清空。

## 语音输入的浏览器要求

- 需要浏览器支持 `SpeechRecognition` / `webkitSpeechRecognition`（Chrome / Edge 支持最好；Firefox 目前不支持）。
- 首次使用要允许麦克风权限；拒绝授权、找不到麦克风、网络断开都会在输入框下方给出明确提示，并且**不会清空你已经输入的文字**，随时可以切回键盘输入。
- 识别中的临时文本实时可见，停止后最终文本留在输入框，由你自己决定何时发送。

## 架构

```
[用户一句话描述]
   ↓
[MiniMax/DeepSeek LLM 思考] → 4 个变体提示词
   ↓
[aixj-image / minimax / jojo / SD] → 4 张预览 PNG
   ↓
[用户选 1 张]
   ↓
[Tripo3D 云端 v3.1] → PBR GLB (SSL 抖动自动重试，失败回落到卡通浮雕)
   ↓
[trimesh 后处理] → 70mm 高的 STL/OBJ/GLB
   ↓
[Three.js 浏览器查看] ← 用户可旋转
   ↓
[/api/print] → 直接在 Bambu Studio 里打开 STL
```

## 项目结构

```
cartoon-print-studio/
├── gui.py                     # 打包入口：PyWebView 原生窗口
├── start.bat                  # 开发模式启动（浏览器）
├── stop.bat
├── README.md
├── backend/                   # FastAPI 服务
│   ├── server.py              # 路由 + health
│   ├── tripo_api.py           # Tripo3D 客户端（polling 容错 + 任务恢复）
│   ├── api_image.py           # aixj/minimax/jojo 适配（多 key 轮换 + 熔断 + 并行出图）
│   ├── bambu.py               # Bambu 启动器（注册表感知）
│   ├── project_store.py       # 本机项目 JSON 存储（原子写入 + 引用校验）
│   ├── software_integrations.py # 桌面软件发现与安全打开
│   ├── mesh_postprocess.py    # 卡通浮雕 + 模型清理
│   ├── triposr_runner.py      # 本地 TripoSR (懒加载，torch 可选)
│   ├── hunyuan_runner.py      # 本地 Hunyuan3D-2 mini (懒加载)
│   ├── sd_client.py           # 本地 SD 1.5 兜底
│   ├── llm_client.py          # MiniMax(.com)/DeepSeek LLM（思考链 + 润色）
│   ├── rmbg_remove.py         # 背景移除
│   ├── bg_remove.py
│   ├── progress.py            # 实时进度事件
│   └── ...
├── frontend/                  # 静态前端
│   ├── index.html             # 主应用（工作台 / 3D / 场景）
│   ├── viewer.html            # 独立 3D 查看器
│   ├── app.js                 # 引擎调度、模型版本、保存、导出
│   ├── workbench.js           # 对话面板 + 无限画布 + 语音 + 润色 + 交付
│   ├── vendor/three/          # 本地 Three.js 运行时（断网可用）
│   └── style.css
├── data/                      # 每个 session 的产物 + projects/ 项目库
│   └── projects/              # 项目 JSON 与上传素材
├── logs/                      # 运行时日志
├── scripts/                   # start_backend.ps1 / stop_backend.ps1 / build.py
├── tasks/                     # 实施计划与流程图
├── installer/
│   ├── build.ps1              # PyInstaller 打包
│   ├── install.ps1            # 部署到 %LOCALAPPDATA% + 桌面快捷方式
│   └── run.spec
├── dist/CartoonPrintStudio/   # PyInstaller 输出
│   ├── CartoonPrintStudio.exe
│   ├── _internal/             # 打包的 Python 依赖
│   │   ├── frontend/          # 打包的前端（含 vendor/three）
│   │   └── backend/           # 打包的后端
│   ├── data/                  # 运行时数据
└── ai/forge-webui/venv/       # 开发用 venv (不在打包里)
```

## API 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET  | `/api/health` | 服务状态 + 所有 key 余额 + dead key 数 |
| GET  | `/api/demo` | 发现本机示例模型，快速进入 3D 工作台 |
| GET  | `/api/printability/{sid}` | 本地检查 STL 网格、体积、尺寸并给出打印提醒 |
| GET  | `/api/bambu` | 探测 Bambu Studio 路径 |
| POST | `/api/bambu` | 手动指定 Bambu 路径 |
| POST | `/api/previews_v2` | 4 张预览（带 LLM 思考） |
| POST | `/api/3d_cartoon` | 本地卡通浮雕（永远可用） |
| POST | `/api/3d_tripo` | Tripo3D 真 3D（带 fallback 建议） |
| POST | `/api/3d_multi` | 多视角 TripoSR 融合 |
| POST | `/api/3d_v2` | 多视角重建（自动生成侧视图） |
| GET  | `/api/engines` | 检查本机 GPU 与各建模引擎可用性 |
| POST | `/api/3d_hy` | Hunyuan3D-2 mini（本地高质） |
| POST | `/api/print` | 打开 STL 进 Bambu Studio |
| GET  | `/api/export/{sid}/{fmt}` | 下载 STL/OBJ/GLB |
| GET  | `/api/progress/{sid}` | 实时进度（SSE 风格） |
| GET  | `/api/session/{sid}/result` | 一次拿完所有产物 |
| GET  | `/api/scenes/config` | 真实场景采集规则、成果格式和 GPU worker 状态 |
| POST | `/api/scenes` | 上传照片/视频并创建真实场景任务 |
| GET  | `/api/scenes/{sceneId}` | 获取真实场景任务状态与采集清单 |
| POST | `/api/scenes/{sceneId}/submit` | 将采集任务提交给 `SCENE_TRAINER_URL` |
| POST | `/api/scenes/{sceneId}/asset` | 导入 GPU worker 生成的 `.ply/.splat/.sog/.spz` |
| GET  | `/api/projects` | 列出本机项目 |
| POST | `/api/projects` | 新建项目 |
| GET  | `/api/projects/{id}` | 读取项目（含缺失引用报告） |
| PUT  | `/api/projects/{id}` | 更新项目 |
| DELETE | `/api/projects/{id}` | 删除项目 |
| POST | `/api/session/from-image` | 用画布合成图创建新的建模会话 |
| POST | `/api/session/{sid}/fork` | 基于当前上下文派生新版本 |
| PUT  | `/api/session/{sid}/edited-model` | 保存 3D 编辑结果并重新导出 |
| POST | `/api/prompt/polish` | 提示词润色（云端不可用时回本机规则） |
| GET  | `/api/software/detect` | 检测本机桌面软件与可用格式 |
| POST | `/api/software/path` | 保存手动修正的软件路径 |
| DELETE | `/api/software/path/{id}` | 恢复自动检测 |
| POST | `/api/software/open` | 把当前版本的文件交给桌面软件（不自动加工） |

## 测试

后端单元测试、浏览器回归和端到端流程都可以独立重跑：

```powershell
# 单元测试（项目存储 / 路径安全 / 网格可打印性 / 软件集成）
python -m unittest discover -s tests

# 浏览器回归：聊天、语音、润色、画布操作、保存恢复、交付确认、320/768/1024/1440 视口
python tests\browser_qa.py --base http://127.0.0.1:8000

# 端到端：画布合成图 → 真实 3D → 新版本 → STL/GLB 导出 → 打印预检
python tests\e2e_flow.py --base http://127.0.0.1:8000 --session <sessionId>
```

浏览器回归的截图留在 `logs/browser-qa/`。

## 部署

### 打包（开发者机器）

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

输出到新的 `release\<版本时间>\` 目录，含可复制到现场电脑的 `CartoonPrintStudio-Portable.zip`。构建不会清理本机 `dist` 或作品数据；安装包不含开发机密钥或用户作品。

### 装到顾客电脑

#### 方式 A：拷贝文件夹

把 `release\<版本时间>\CartoonPrintStudio-Portable.zip` 复制到顾客电脑并解压，然后运行包内 `install.ps1`。也可以直接复制旁边的 `CartoonPrintStudio\` 文件夹并运行其中的 exe。

安装脚本已包含在 ZIP 中。也可以指定解压后的程序目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -BundleDir .\CartoonPrintStudio
```

默认装到 `%LOCALAPPDATA%\CartoonPrintStudio\`，并在桌面创建快捷方式。每台电脑各自配置 API key，作品库和生成文件也按电脑独立保存。升级会保留这些数据，不会清理安装目录里的用户文件。

### 顾客电脑上需要的依赖

- **WebView2 Runtime**（Win11 自带；Win10 缺失时 exe 第一次启动会引导下载）
- **Bambu Studio**（任何常见安装位置都可，应用自动检测）
- **网络**（如果要用云端 Tripo3D / minimax 预览）
- **离线场景**：卡通浮雕 / TripoSR / Hunyuan3D（要 GPU）都能用，仅缺预览图
- **Tripo 与云端预览**：每台电脑单独在 `%LOCALAPPDATA%\CartoonPrintStudio\keys.txt` 配置获授权的 API key；没有 key 时仍可打开离线 demo、编辑和使用本机浮雕流程

### 安装包包含 / 不包含

**包含**: FastAPI, uvicorn, trimesh, pillow, scipy, scikit-image, PyWebView, Tripo 客户端, 本地 Three.js 前端、一个离线体验模型和打印预览。**不包含**任何 API 密钥。

**不包含**: torch / diffusers (~2 GB 本地 SD), Hunyuan3D / TripoSR 模型权重（懒加载，本地 3D 路径需要联网拉权重）。Hunyuan3D-2 mini 还需要 `accelerate`；云端 provider 覆盖这些路径，离线仍能用卡通浮雕。

## 故障排查

| 症状 | 解决 |
|---|---|
| 双击 exe 无反应 | 装 WebView2 Runtime (<https://developer.microsoft.com/microsoft-edge/webview2/>) |
| "Tripo3D credits low" | 余额 < 30 credits；改用引擎选 "卡通浮雕" |
| jojo 报余额不足 | 正常 — 应用自动标 dead 1 小时，转 minimax / aixj |
| aixj 生成失败 | 自动重试 1 次，仍失败转 minimax（gpt-image-2 偶发 TLS 握手超时） |
| minimax 也挂了 | 等服务恢复或换网络；本地 SD 兜底 |
| Bambu 没自动打开 | 看 `/api/bambu` 返回的路径是否正确；用 `POST /api/bambu` 手动指定 |
| 模型倒了 / 质量差 | Tripo3D 是云端 AI 有随机性；多试几次 prompt 调整 |

## License

MIT
