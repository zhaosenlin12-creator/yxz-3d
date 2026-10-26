# 宜小智工作台（pingdou-workstation）

一个「对话 → 创作预览 → 画布编辑 → 3D 模型 / 激光切割名片 → 打开本机软件」的完整工作台。

- **airi**：对话前端（Vue3 + live2d 宜小智），dev 端口 `5199`
- **cartoon-print-studio**：后端能力服务（FastAPI），端口 `8000`，提供生图预览、3D 建模、激光名片 SVG、本机软件检测与打开

---

## 快速开始（本机）

```powershell
# 1) 一键启动后端 + 前端（自动读 keys.txt，自动打开浏览器）
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

打开后即 http://127.0.0.1:5199 —— 与宜小智对话；需要做 3D 摆件或激光名片时按提示操作。

## 快速开始（新电脑）

1. 安装 Git、Node.js 20+（`corepack enable`）、Python 3.10/3.11（Add to PATH）
2. 解压 `pingdou-workstation.zip` 到任意目录
3. 运行 `install-new-pc.ps1`（自动 pnpm install + 创建 venv + pip install）
4. 运行 `start-all.ps1`

> ⚠️ **keys.txt 必须随包携带**（不入 GitHub）：文件在 `cartoon-print-studio\keys.txt`，
> 含带标签的 API key（`minimax-key:` / `minimax-key-2:` 用于 LLM、`deepseek-key:` LLM 备用、
> `aixj-image-key:` 生图首选、`minimax-image-key:` 生图备用、`jojo-image-key:`、`TRIPO:` 3D）。
> 缺失时生图/对话会降级或失败，请从原电脑拷贝。

## 目录结构

```
pingdou-workstation/
├── start-all.ps1            # 一键启动（端口冲突/依赖缺失有明确兜底提示）
├── install-new-pc.ps1       # 新电脑安装
├── backend-requirements.txt # 后端 Python 依赖冻结清单
├── README.md
├── airi/                    # 前端 monorepo（含 .git）
└── cartoon-print-studio/    # 后端（含 .git、keys.txt、data/laser/template 名片模板）
```

## 配置说明（跑服务自动读取）

| 配置项 | 位置 | 说明 |
|---|---|---|
| LLM / 生图 / TTS API key | `cartoon-print-studio\keys.txt` | 按行标签分类：`minimax-key:`/`minimax-key-2:`(LLM)、`deepseek-key:`(LLM 备用)、`aixj-image-key:`(生图首选)、`minimax-image-key:`(生图备用)、`jojo-image-key:`、`TRIPO:`(3D) |
| 后端依赖 | `backend-requirements.txt` | 已冻结；torch/torchvision 的 `+cu121` 版本需从 PyTorch 官方索引安装（`install-new-pc.ps1` 已自动加 `--extra-index-url https://download.pytorch.org/whl/cu121`） |
| 生图策略 | 后端 `backend/api_image.py` | aixj 优先 → minimax 备用 → 本地 SD 兜底；失败自动切换 |
| LLM 策略 | 后端 `backend/llm_client.py` | MiniMax(.com) → DeepSeek → 本地规则 兜底 |
| 前端 API 地址 | 环境变量 `VITE_CARTOON_PRINT_API` | 默认 `http://127.0.0.1:8000`（`start-all.ps1` 自动注入） |
| 数据目录 | 环境变量 `CARTOON_DATA_DIR` / `CARTOON_ROOT` | 默认项目内 `data/` |
| 软件路径 | 自动检测注册表/快捷方式/常见路径；用户修正存 `data/software_paths.json` | Bambu Studio(3D/STL)、xTool Studio(激光/PNG、SVG)、LightBurn、LaserGRBL、Orca/Prusa/Cura、Blender |
| 3D 引擎 | `tripo` key / 本地 TripoSR / Hunyuan3D-2 | key 缺失自动降级本地 |

## 关键流程（已验收）

1. **对话**：宜小智思考走真实 LLM（MiniMax→DeepSeek），语音 TTS 走 MiniMax speech
2. **3D 摆件**：聊天创作面板 → 描述 → 4 张生图预览（aixj）→ 画布编辑器（加字/个性化）→ 应用到 3D → 生成 STL/GLB → 检测本机软件 → 打开 Bambu Studio
3. **激光切割名片**：聊天输入区左下「+」→「激光切割名片」→ 选模板（背面固定活动蓝底图，正面可编辑姓名/职位/单位/联系方式/标语/配色）→ 生成切割文件（856×540px，SVG 用 mm 单位，含外切割红线/内雕刻绿线/定位十字）→ 预览 → 检测本机激光软件 → 打开 xTool Studio / LightBurn

## 失败兜底设计

- **端口冲突**：`start-all.ps1` 检测到 8000/5199 被占用会跳过启动并提示，不盲目杀进程
- **软件未安装**：交付面板只列出「已检测到」的软件；未检测到给出手动下载提示；用户可在面板手动指定 exe 路径（存 `software_paths.json`）
- **API key 缺失/失效**：生图 aixj→minimax→本地 SD 三级兜底；LLM MiniMax→DeepSeek→本地规则；jojo 余额耗尽自动熔断跳过
- **导出文件未生成**：打开软件前校验文件存在，缺失时提示先生成
- **首次冷启动慢**：vite 首次编译可能 30-90 秒，`start-all.ps1` 会等待就绪再打开浏览器

## GitHub

- **合并仓库已推送**：`origin = https://github.com/zhaosenlin12-creator/yxz-3d.git`（分支 `main`，提交 `d75c7b3`）
- 仓库包含 airi 前端 + cartoon-print-studio 后端源码、启动/安装脚本、README、依赖清单、名片模板（`data/laser/template`）
- ⚠️ **隐私红线（已用 .gitignore 强制排除）**：`keys.txt`、`software_paths.json`、`.glb/.obj/.stl` 大模型均不入库。克隆仓库后需从原电脑拷贝 `cartoon-print-studio\keys.txt`；角色大模型（`data/yxz_character_tripo_jpg/`）随 ZIP 交付，不在 GitHub。
- ⚠️ 提交前始终检查：`git status` 中出现 `keys.txt` 即禁止 `git add`；仓库根 `.gitignore` 已含 `**/keys.txt` 规则，勿删除。

## 大模型 / 运行数据（不入 GitHub）

| 资源 | 位置 | 说明 |
|---|---|---|
| 角色 3D 模型 | `cartoon-print-studio\data\yxz_character_tripo_jpg\model` | 宜小智角色主模型（GLB/OBJ/STL），ZIP 自带，不入 GitHub |
| API keys | `cartoon-print-studio\keys.txt` | 随 ZIP；克隆仓库后需手动放入 |
| 名片模板 | `cartoon-print-studio\data\laser\template\activity_blue.png` | 已入 GitHub（源码资产） |
| 软件路径修正 | `cartoon-print-studio\data\software_paths.json` | 每台机器自动检测并可按需生成，不入库 |
