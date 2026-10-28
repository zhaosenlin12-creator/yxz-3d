# 宜小智工作台（pingdou-workstation）

一个「对话 → 创作预览 → 画布编辑 → 3D 模型 / 激光切割名片 → 打开本机软件」的完整工作台。

- **airi**：对话前端（Vue3 + 3D 宜小智），dev 端口 `5199`
- **cartoon-print-studio**：后端能力服务（FastAPI），端口 `8000`，提供生图预览、3D 建模、激光名片 SVG、本机软件检测与打开

---

## 一、首次安装（新电脑 / 全新环境）

> ⚠️ **前提**：仓库里**不含**后端 Python 环境，也**不含** AI 模型权重（都被 `.gitignore` 排除，只随作者发布的 zip 提供）。
> 第一次启动必须联网拉依赖（约 6GB）和模型权重（约 9GB）。

### 第 0 步：系统前提（一次性）

| 软件 | 版本要求 | 下载 | 检查命令 |
|---|---|---|---|
| Git | 任意较新版本 | https://git-scm.com | `git --version` |
| Node.js | **20 或以上** | https://nodejs.org | `node -v` |
| Python | **3.12（推荐）/ 3.11** | https://python.org | `python --version` |
| uv（可选但强烈建议） | 任意 | https://docs.astral.sh/uv/ | `uv --version` |

> **Python 版本说明**：`backend-requirements.txt` 里的 `contourpy==1.3.3` / `numpy==2.5.2` 已经要求 **Python ≥ 3.11**，
> 3.10 会直接装不上。脚本会自动按 `3.12 > 3.11` 挑选本机已装的解释器。
>
> **uv 的作用**：pip 的新版解析器在这种「全量 freeze 快照」上会做指数级回溯（实测卡在 `aiohttp` 上 10 分钟不收敛）；
> uv 解析同一份文件 **5 秒**出结果，下载并行且可断点续传。没有 uv 时脚本会自动回退到 pip（慢很多）。

### 第 1 步：拉代码

```bash
git clone https://github.com/zhaosenlin12-creator/yxz-3d.git
cd yxz-3d
```

### 第 2 步：一键安装并启动

**双击「INSTALL-FIRST-TIME.bat」**，或手动：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File install-new-pc.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File start-all.ps1
```

安装脚本会自动完成：

1. 检查 Node / Git / Python / pnpm / uv
2. 配国内镜像（pip 清华源、npm npmmirror、Electron 镜像）
3. 建 Python 3.12 venv，**用 uv** 装 `backend-requirements.txt`（torch 从本地 wheel 装，不走网络）
4. `pnpm install --filter '@proj-airi/stage-web...'` 只装前端需要的依赖闭包
5. 预置静态资源（VRM / Live2D / MediaPipe）
6. 下载 AI 模型权重（SD 1.5 / Hunyuan3D-2 mini / TripoSR，约 9GB，支持断点续传）

> **断点续装**：依赖清单 / Python 版本 / torch 通道都没变时，安装步骤**秒级跳过**。
> 想强制重装用 `-Force`；只想补模型权重用 `-OnlyModels`；不想下模型用 `-SkipModels`。

### 第 3 步：验证

| 检查项 | 方法 | 期望 |
|---|---|---|
| 后端 | 浏览器打开 `http://127.0.0.1:8000/api/software/detect` | 返回 JSON（`tools` 数组） |
| 前端 | 浏览器打开 `http://127.0.0.1:5199` | 看到宜小智对话界面 + 会动的宜小智形象 |
| 预制模型 | `http://127.0.0.1:8000/api/presets/models` | 返回 3 个 pose_* 模型 |
| 日志 | `.run\backend-8000.err.log`、`.run\frontend-5199.err.log` | 无致命报错 |

> 端口 8000 被别的程序占用时，脚本会**自动顺延**到 8001/8002 并把真实端口注入前端，日志里会写明。

---

## 二、日常启动（装过一次之后）

**双击「START.bat」**，等价于：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File start-all.ps1
```

- 前后端**并行**启动、并**并行**等待就绪；已在运行时直接复用，不重复拉起。
- 端口被占用自动顺延，不会误杀其它进程。
- 自动打开浏览器。停止用 `stop-all.ps1`（或双击后 Ctrl+C）。

常用参数：

```powershell
pwsh -File start-all.ps1 -NoBrowser      # 不自动开浏览器
pwsh -File start-all.ps1 -NoBackend      # 只起前端
pwsh -File start-all.ps1 -BackendPort 8100
```

---

## 三、目录里的脚本

| 文件 | 作用 |
|---|---|
| `START.bat` | 日常启动（双击） |
| `INSTALL-FIRST-TIME.bat` | 新机器：安装 + 启动（双击） |
| `install-new-pc.ps1` | 装依赖（uv / 镜像 / 断点续装 / 模型权重） |
| `fetch-models.ps1` | 只下 AI 模型权重（SD 1.5 / Hunyuan3D / TripoSR） |
| `start-all.ps1` | 起前后端 + 就绪探测 + 自动开浏览器 |
| `stop-all.ps1` | 停掉前后端 |
| `lib-common.ps1` | 共用函数（端口探测 / 镜像 / 断点续传下载 / uv 封装） |

---

## 四、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 双击后窗口一闪就关 | 直接双击了 .ps1 | 双击 `.bat`；或在终端里 `pwsh -File start-all.ps1` 看报错 |
| 安装很慢 / 卡在 aiohttp | pip 解析器指数级回溯 | 装 `uv`（`pip install uv`）后重跑，解析从 10 分钟降到 5 秒 |
| torch 下载卡住不动 | pip 走 download.pytorch.org 会零字节卡死 | 脚本已改为先落到本地 wheel 缓存再离线安装；缓存目录见 `YXZ_CACHE_DIR` |
| 提示「端口 8000 被其它程序占用」 | 别的服务占了 8000 | 脚本会自动顺延到 8001，**不需要**手动处理 |
| 页面打开但对话/生图报错 | `keys.txt` 缺失或 key 失效 | 确认 `cartoon-print-studio\keys.txt` 存在（见下） |
| 本地生图不可用 | SD 1.5 权重没下全 | 跑 `pwsh -File fetch-models.ps1 -Only sd`，看 `.run` 下日志 |
| 本地 3D 生成不可用 | Hunyuan3D / TripoSR 权重缺失 | `pwsh -File fetch-models.ps1 -Only hunyuan` / `-Only triposr` |
| 舞台形象是「黑影」 | 旧的 VRM 形象缺失（.gitignore 排除） | 舞台形象已改成 **2D 分层精灵**，不再依赖 VRM；仅预览页需要 3D 时再从作者 zip 拷 `airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm` |
| 宜小智 表情/眼神不动 | 浏览器缓存了旧的精灵图 | `Ctrl+Shift+R` 强制刷新；精灵层在 `airi/packages/stage-ui/src/assets/yxz/layers/` |
| 打开软件按钮无效 | 新电脑没装对应软件 | 交付面板会列出已检测到的软件；未检测到时手动指定 exe 路径（存 `data/software_paths.json`） |

---

## 五、配置说明（跑服务自动读取，不写死）

| 配置项 | 位置 | 说明 |
|---|---|---|
| LLM / 生图 / 3D API key | `cartoon-print-studio\keys.txt` | 按行标签分类：`minimax-key:`/`minimax-key-2:`(LLM)、`deepseek-key:`(LLM 备用)、`aixj-image-key:`(生图首选)、`minimax-image-key:`(生图备用)、`jojo-image-key:`、`TRIPO:`(3D 首选，值需为 `tsk_...`)、`hunyuan3d-secret-id:`/`hunyuan3d-secret-key:`(3D 备用)；详见第十节 |
| API key 空白模板 | `cartoon-print-studio\keys.txt.example` | 仓库内可提交；`install-new-pc.ps1` 发现缺 `keys.txt` 时会自动复制一份，填完 key 重启后端即生效 |
| 后端依赖 | `backend-requirements.txt` | 已冻结；`open-clip-torch` 因 `protobuf<4` 与 `onnxruntime` 冲突，单独用 `--no-deps` 安装 |
| 镜像 | `install-new-pc.ps1 -PypiIndex / -NpmRegistry` | 默认清华源 + npmmirror；`-SlowNetwork` 走官方源 |
| 下载缓存 | 环境变量 `YXZ_CACHE_DIR` | 默认 `%LOCALAPPDATA%\yxz-3d-cache`；torch wheel 等大文件缓存在这里，可拷贝到新机器复用 |
| HF 镜像 | `fetch-models.ps1 -Mirror` | 默认 `https://hf-mirror.com`；直连 huggingface.co 在国内基本不可达 |
| 生图策略 | 后端 `backend/api_image.py` | aixj 优先 → minimax 备用 → 本地 SD 兜底；失败自动切换 |
| LLM 策略 | 后端 `backend/llm_client.py` | MiniMax(.com) → DeepSeek → 本地规则 兜底 |
| 3D 引擎 | 后端 `backend/` tripo/hunyuan runner | Tripo → 混元3D → 本地彩色 三级自动切换 |
| 前端 API 地址 | 环境变量 `VITE_CARTOON_PRINT_API` | 默认 `http://127.0.0.1:8000`（start-all.ps1 自动注入实际端口） |
| 软件路径 | 自动检测注册表/快捷方式/常见路径；修正存 `data/software_paths.json` | Bambu Studio、xTool Studio、LightBurn、LaserGRBL、Orca/Prusa/Cura、Blender |

---

## 六、关键流程

1. **对话**：宜小智思考走真实 LLM（MiniMax→DeepSeek），语音 TTS 走 MiniMax speech
2. **3D 摆件**：聊天创作面板 → 描述 → 生图预览（aixj）→ 画布编辑器（加字/个性化/批注）→ 应用到 3D → 生成 STL/GLB → 检测本机软件 → 打开 Bambu Studio
3. **激光切割卡片**：聊天输入区左下「+」→「激光切割卡片」→ 打开「激光切割工作台」五步流程（对话确定作品 → 生成作品预览 → 创作面板产出 3D → 导出切割 SVG → xTool 切割）→ 工作台「开始对话引导」把作品需求直接发给宜小智，逐轮确认后由智能体产出预览 → 预览卡下方「打开创作面板」批注编辑并生成 3D 效果 → 回到工作台导出切割文件（SVG mm 单位，含切割红线/雕刻绿线/定位十字）→ 检测本机激光软件 → 打开 xTool Studio / LightBurn
   - 卡片正面是**用户自己的作品图**，背面是**活动主视觉背景**，尺寸随背面模板（`activity_stage` 为 100 × 56.25 mm）
   - 背面模板随仓库发布在 `cartoon-print-studio/backend/assets/laser/`，后端启动时自动补齐到 `data/laser/template/`，克隆即可用
   - **正面和背面都可以用 AI 现画**：工作台「导出激光切割卡片」里分别有「AI 生成正面」和「AI 生成背景」，用一句话描述想要的风格（例：深蓝科技感、星辰与电路板、卡通插画风），后端出图后自动登记为模板，随时可换；不生成也能用纯色版式
   - 正面版式为**满幅作品 + 底部信息栏**（姓名大标题 / 身份学校 / 右侧联系方式 / 标语），不再左右硬分割
4. **3D 打印作品**：聊天输入区左下「+」→「3D 打印作品」→ 打开「3D 打印工作台」，与激光切割共用同一条「对话引导 → 预览 → 创作面板 → 3D → 导出 STL → 切片打印」链路
5. **预制模型**：「+」→「宜小智 3D 模型」→ 打开 `/yxz-vrm-preview` 直接看主项目同款 3D 形象；工作台「宜小智预制 3D 模型示例」里的三个摆件（招手打招呼 / 双手叉腰 / 举手敬礼）就是**真正的宜小智机器人**，模型文件随仓库发布在 `presets/models/<pose>/`，可点「3D 预览」旋转查看、可直接下载 STL 去打印
6. **生成 3D 的阶段进度**：点「开始生成 3D 模型」后，卡片会按「准备中 → 生成立体结构 → 上色与细节 → 打印优化 → 完成」分阶段推进，实时显示阶段、百分比和已用时长，3D 视图里同时给出设计稿预览；失败时卡片会明确报错并提供「再试一次」，不会一直卡在「正在制作效果」

---

## 七、GitHub 与隐私

- 仓库：`https://github.com/zhaosenlin12-creator/yxz-3d.git`（分支 `main`）
- ⚠️ **不入 GitHub**（.gitignore 已强制排除）：`keys.txt`、`software_paths.json`、本地 AI 权重、运行期生成的名片背景图
- **已入库**：`presets/models/` 里的宜小智预制摆件（GLB + STL + 缩略图）、`presets/images/` 角色渲染图、`cartoon-print-studio/backend/assets/laser/` 名片模板
- 克隆仓库后需从原电脑拷贝 `cartoon-print-studio\keys.txt`；角色 VRM 主形象随 ZIP 交付
- 提交前检查：`git status` 出现 `keys.txt` 即禁止 `git add`；勿删除根 `.gitignore` 中的 `**/keys.txt` 规则

## 八、大模型 / 运行数据（不入 GitHub）

| 资源 | 位置 | 说明 |
|---|---|---|
| 角色 3D 模型 | `airi/packages/stage-ui-three/src/assets/vrm/models/yxz.vrm` | 宜小智主角模型，ZIP 自带；缺失时脚本用公开 VRM 样例占位 |
| 宜小智 2D 精灵层 | `airi/packages/stage-ui/src/assets/yxz/layers/` | 已入库：`body.png`（含光环的整身）、`glow.png`（光环辉光）、`eye_l/eye_r`、`mouth_*`、`manifest.json` |
| 精灵切图脚本 | `airi/scripts/yxz-rebuild/cut_sprite_layers.py` | 从 `front-wave.png` 重新切层；改图后重跑即可再生成整套精灵 |
| API keys | `cartoon-print-studio/keys.txt` | 随 ZIP；克隆后需手动放入 |
| 名片模板 | `cartoon-print-studio/data/laser/template/activity_blue.png` | 缺失时后端 `/api/laser_card` 会报错 |
| 预制摆件模型 | `presets/models/<pose>/*` | **已入库**（真正的宜小智机器人）；重跑脚本可重建：见下方「重建预制模型」 |
| SD 1.5 权重 | `cartoon-print-studio/ai/forge-webui/models/Stable-diffusion/` | `fetch-models.ps1` 下载 |
| SD 1.5 diffusers 配置 | `cartoon-print-studio/ai/forge-webui/backend/huggingface/runwayml/stable-diffusion-v1-5/` | `fetch-models.ps1` 下载；缺 `feature_extractor/preprocessor_config.json` 时本地 SD 起不来 |
| Hunyuan3D-2 mini | `~/.cache/huggingface/hub/models--tencent--Hunyuan3D-2mini/` | `fetch-models.ps1` 下载 |
| TripoSR | `cartoon-print-studio/models/cache/models/AI-ModelScope--TripoSR/` | `fetch-models.ps1` 下载 |
| 软件路径修正 | `cartoon-print-studio/data/software_paths.json` | 每台机器自动检测生成，不入库 |

---

## 九、宜小智动态形象（2D 分层精灵）

舞台上的宜小智不是 3D VRM，而是一套 **PNG 差分精灵**：一张完整的原画 + 抠出来的眼睛、嘴、光环辉光，
用 Canvas 2D 实时合成并驱动。这套做法的好处是形象永远和原画完全一致（不会出现建模走形），
同时眼神、眨眼、说话口型、呼吸、摇摆、光环呼吸都是真动。

| 层 | 文件 | 作用 |
|---|---|---|
| 身体 | `body.png` | **原画整张**（光环已焊进身体），头盔 100% 完整，绝不会出现接缝裂开 |
| 光环辉光 | `glow.png` | 头顶光环洒出的光晕，用叠加模式（`lighter`）画在身体之上，缓慢呼吸 |
| 眼睛 | `eye_l.png` / `eye_r.png` | 跟随鼠标 gaze + 自动眨眼 + 按状态收窄 |
| 嘴 | `mouth_*.png` | 微笑 / 说话 A-B-C / 张嘴 / 咧嘴 / 小嘴，按状态与音量切换 |

- 组件：`airi/packages/stage-ui/src/components/scenes/YXZPetScene.vue`
- 坐标：`airi/packages/stage-ui/src/assets/yxz/layers/manifest.json`（切图时自动写出，位置不会漂）
- 重新切图（改了 `front-wave.png` 之后）：

```powershell
cartoon-print-studio\ai\forge-webui\venv\Scripts\python.exe `
    airi\scripts\yxz-rebuild\cut_sprite_layers.py
```

> 切图脚本用「头盔轮廓几何拟合」把光环和身体分开：**光环整张留在身体层**，
> 所以呼吸/摇摆时两层绝不会错位；会动的只有叠加的辉光。

---

## 九·五、重建宜小智预制摆件模型

`presets/models/<pose>/` 里的三个摆件（招手打招呼 / 双手叉腰 / 举手敬礼）是用真实角色渲染图跑
**混元3D 云端** image-to-3D 得到的，不是手搓模型。重跑脚本：

```powershell
# 只做「AI 去掉头顶光环/星星」的图片清理
cartoon-print-studio\ai\forge-webui\venv\Scripts\python.exe `
    cartoon-print-studio\scripts\build_preset_models.py --stage images

# 用清理后的图重建 3D 模型（走混元3D 云端，约 5 分钟/个）
cartoon-print-studio\ai\forge-webui\venv\Scripts\python.exe `
    cartoon-print-studio\scripts\build_preset_models.py --stage models

# 只重调材质（不重新生成，几秒钟）
cartoon-print-studio\ai\forge-webui\venv\Scripts\python.exe `
    cartoon-print-studio\scripts\build_preset_models.py --stage retouch
```

几个关键点：

- **光环必须先去掉**。头顶的光环和星星在 image-to-3D 时会粘到头盔上，把头盔劈成两半，
  所以脚本先让 AI 把它们抹掉（结果落在 `presets/build/<pose>_clean.png`），再送去建模。
- **默认关闭 PBR**（`--pbr` 可以打开）。PBR 导出把金属度烘焙成 1、粗糙度烘焙成 0，
  渲染出来是一坨镜面铬；关掉之后才是设计稿里那种干净的白漆质感，文件还小三分之一。
- **材质再抹一遍**。`mesh_postprocess.make_matte_material()` 会把金属度压到 0、粗糙度提到 0.62，
  并丢掉那张全红的 metallic/roughness 贴图。

---

## 十、配置 API Key（后端完全可用）

后端所有联网能力都读同一个文件：`cartoon-print-studio\keys.txt`。
**这个文件已被 `.gitignore` 排除，永远不会进 GitHub。**

克隆仓库后：

1. 复制仓库内的空白模板（安装脚本在你没建 `keys.txt` 时会自动复制）：

```powershell
copy cartoon-print-studio\keys.txt.example cartoon-print-studio\keys.txt
```

2. 打开 `keys.txt`，把冒号后面填上真实 key，保存：

| 标签 | 用途 | 缺失时 |
|---|---|---|
| `minimax-key:` / `minimax-key-2:` | 对话 LLM、流式思考、口播文案、TTS | 回退 DeepSeek → 本地规则 |
| `deepseek-key:` | 对话 LLM 备用 | 回退本地规则 |
| `aixj-image-key:` | 生图（3D 摆件预览图）首选 | 回退 minimax → 本地 SD 1.5 |
| `aixj-image-key-2:` | 生图备用（同一服务的第二把） | 同上 |
| `minimax-image-key:` / `jojo-image-key:` | 生图备用 | 同上 |
| `TRIPO:` | 云端高质量 3D 生成首选 | 回退混元 3D → 本地 Hunyuan3D / TripoSR |
| `hunyuan3d-secret-id:` / `hunyuan3d-secret-key:` | 混元 3D 云端备用 | 同上 |

3. 生图 key 多把出错（比如某一把返回 403，说明那个分组没开生图）时，
   后端会自动换下一把——主备两把一起填更稳。MiniMax 生图只认 `sk-cp-` 开头的平台 key。

### 前端对话也要 key（同一批 key，换个地方放）

AIRI 舞台的对话是浏览器直连 provider，凭据存在浏览器里，手填一次很麻烦。
仓库支持一个**本地种子文件**，放好就自动生效：

```powershell
copy airi\apps\stage-web\public\provider-seed.json.example airi\apps\stage-web\public\provider-seed.json
```

填上和后端同一批 key：

```json
{
  "providers": {
    "minimax":  { "apiKey": "<sk-cp- 开头>", "baseUrl": "https://api.minimaxi.com/v1/" },
    "deepseek": { "apiKey": "<sk- 开头>",    "baseUrl": "https://api.deepseek.com/" }
  },
  "activeProvider": "minimax",
  "activeModel": "MiniMax-M2.7"
}
```

`provider-seed.json` 同样被 `.gitignore` 排除，不会进 GitHub。
启动时应用会自动读取它：**只填空缺，不会覆盖你在设置界面里手填过的 key**；
配好了 provider，首次引导弹窗也会自动跳过。

3. 重启后端（`start-all.ps1`）即可生效。留空的项会被自动跳过，**不会报错**，只是走本地兜底。

> 也可以用环境变量覆盖：`MINIMAX_API_KEY`、`DEEPSEEK_API_KEY`、`TRIPO3D_KEY`、
> `HUNYUAN3D_SECRET_ID`、`HUNYUAN3D_SECRET_KEY`。
