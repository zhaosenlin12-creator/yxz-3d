# 宜小智工作台（pingdou-workstation）

一个「对话 → 创作预览 → 画布编辑 → 3D 模型 / 激光切割名片 → 打开本机软件」的完整工作台。

- **airi**：对话前端（Vue3 + 3D 宜小智），dev 端口 `5199`
- **cartoon-print-studio**：后端能力服务（FastAPI），端口 `8000`，提供生图预览、3D 建模、激光名片 SVG、本机软件检测与打开

---

## 一、首次安装（新电脑 / 全新环境）—— 按顺序操作

> ⚠️ **关键前提**：`pingdou-workstation.zip` 内**不含后端 Python 环境**（torch 等约 2GB，无法随包携带）。解压后第一次启动必须联网安装，**不要**一解压就直接双击「启动.bat」。

### 第 0 步：确认系统前提已安装（一次性）

| 软件 | 版本要求 | 下载 | 检查命令 |
|---|---|---|---|
| Git | 任意较新版本 | https://git-scm.com | `git --version` |
| Node.js | **20 或以上** | https://nodejs.org | `node -v` |
| Python | **3.10 或 3.11**（勾选 Add to PATH） | https://python.org | `python --version` |

> 安装 Python 时**务必勾选「Add python.exe to PATH」**；Node 装完后在终端执行一次 `corepack enable`。

### 第 1 步：解压

把 `pingdou-workstation.zip` 解压到任意目录（如 `C:\workstation`）。解压后目录里应有：

```
C:\workstation\
├── 启动.bat                 # 已安装好后：双击启动
├── 一键安装并启动.bat       # 新电脑：双击自动安装 + 启动
├── start-all.ps1
├── install-new-pc.ps1
├── backend-requirements.txt
├── README.md
├── airi/                    # 前端
└── cartoon-print-studio/    # 后端（含 keys.txt、名片模板）
```

> 确认 `cartoon-print-studio\keys.txt` 存在（API key 文件，随 zip 自带；若缺失从原电脑拷贝）。

### 第 2 步（方式 A，推荐）：双击「一键安装并启动.bat」

自动完成：① 检查 Node/Git/Python → ② 前端 `pnpm install`（数百 MB）→ ③ 后端建 venv + `pip install`（约 2GB，torch 较大）→ ④ 启动前后端并打开浏览器。

- 全程**联网**，预计 20~40 分钟（取决于网速），窗口里会显示每步 OK/FAIL。
- **不要中途关闭窗口**。若失败，看第 3 步手动分步。

### 第 2 步（方式 B）：手动分步（更稳，推荐排障时用）

打开 PowerShell（或 cmd），进入解压目录后依次执行：

```powershell
# ① 安装依赖（前端 + 后端，需联网，时间较长）
powershell -NoProfile -ExecutionPolicy Bypass -File install-new-pc.ps1

# ② 启动前后端（自动打开浏览器）
powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1
```

### 第 3 步：验证是否启动成功

| 检查项 | 方法 | 期望 |
|---|---|---|
| 后端 | 浏览器打开 `http://127.0.0.1:8000/api/software/detect` | 返回 JSON（非报错） |
| 前端 | 浏览器打开 `http://127.0.0.1:5199` | 看到宜小智对话界面 |
| 日志 | 解压目录下的 `.run\backend-8000.err.log`、`.run\frontend-5199.err.log` | 无致命报错 |

前端首次冷编译可能需要 30~90 秒，请耐心等窗口提示「前端就绪」。

---

## 二、日常启动（装过一次之后）

**双击「启动.bat」**即可，等价于：

```powershell
powershell -ExecutionPolicy Bypass -File start-all.ps1
```

- 端口被占用时脚本会提示「已占用（跳过启动）」，不会误杀其它进程。
- 自动读取 `cartoon-print-studio\keys.txt` 的 API key，自动打开浏览器。

---

## 三、常见问题（双击失败排查表）

| 现象 | 原因 | 处理 |
|---|---|---|
| 双击后窗口一闪就关 | 未解压就直接双击了 .ps1，或运行环境问题 | 用「启动.bat」/「一键安装并启动.bat」双击；不要直接双击 .ps1 |
| 双击后长时间没反应、像卡住 | 首次启动正在自动安装后端依赖（torch 约 2GB） | 耐心等待 10~30 分钟；或先手动跑 `install-new-pc.ps1` 看进度 |
| 提示「pip install 失败」 | 网络超时 / Python 版本不对 / 磁盘不足 | 重跑 `install-new-pc.ps1`（断点续装）；确认 Python 3.10/3.11；预留 5GB 空间 |
| 提示「pnpm install 失败」 | 网络问题 / Node 版本过旧 | 重试；确认 Node 20+ 且执行过 `corepack enable` |
| 提示「未找到 Node.js / Git / Python」 | 系统前提未装 | 按「第 0 步」安装后重试 |
| 前端一直「等待就绪」超时 | 首次冷编译慢 / vite 启动报错 | 查看 `.run\frontend-5199.err.log`；确认网络可访问 npm registry |
| 页面打开但对话/生图报错 | keys.txt 缺失或 key 失效 | 确认 `cartoon-print-studio\keys.txt` 存在且格式正确（见下） |
| 打开软件按钮无效 | 新电脑没装对应软件 / 路径变了 | 交付面板会列出「已检测到」的软件；未检测到时面板会提示手动指定 exe 路径（存 `data/software_paths.json`，每台机器自动适配，不需改代码） |

---

## 四、配置说明（跑服务自动读取，不写死）

| 配置项 | 位置 | 说明 |
|---|---|---|
| LLM / 生图 / 3D API key | `cartoon-print-studio\keys.txt` | 按行标签分类：`minimax-key:`/`minimax-key-2:`(LLM)、`deepseek-key:`(LLM 备用)、`aixj-image-key:`(生图首选)、`minimax-image-key:`(生图备用)、`jojo-image-key:`、`TRIPO:`(3D 首选)、`HUNYUAN3D:`(3D 备用) |
| 后端依赖 | `backend-requirements.txt` | 已冻结；torch/torchvision 的 `+cu121` 版本需从 PyTorch 官方索引安装（install-new-pc.ps1 已自动加 `--extra-index-url`） |
| 生图策略 | 后端 `backend/api_image.py` | aixj 优先 → minimax 备用 → 本地 SD 兜底；失败自动切换 |
| LLM 策略 | 后端 `backend/llm_client.py` | MiniMax(.com) → DeepSeek → 本地规则 兜底 |
| 3D 引擎 | 后端 `backend/` tripo/hunyuan runner | Tripo → 混元3D → 本地彩色 三级自动切换 |
| 前端 API 地址 | 环境变量 `VITE_CARTOON_PRINT_API` | 默认 `http://127.0.0.1:8000`（start-all.ps1 自动注入） |
| 软件路径 | 自动检测注册表/快捷方式/常见路径；修正存 `data/software_paths.json` | Bambu Studio(3D/STL)、xTool Studio(激光)、LightBurn、LaserGRBL、Orca/Prusa/Cura、Blender——每台机器自动检测，不写死 |

---

## 五、关键流程（已验收）

1. **对话**：宜小智思考走真实 LLM（MiniMax→DeepSeek），语音 TTS 走 MiniMax speech
2. **3D 摆件**：聊天创作面板 → 描述 → 生图预览（aixj）→ 画布编辑器（加字/个性化/批注）→ 应用到 3D → 生成 STL/GLB → 检测本机软件 → 打开 Bambu Studio
3. **激光切割名片**：聊天输入区左下「+」→「激光切割名片」→ 选模板（背面固定活动蓝底图，正面可编辑）→ 生成切割文件（SVG mm 单位，含切割红线/雕刻绿线/定位十字）→ 预览 → 检测本机激光软件 → 打开 xTool Studio / LightBurn
4. **预制模型**：「+」→「宜小智 3D 模型」→ 打开 `/yxz-vrm-preview` 直接看主项目同款 3D 形象（轻动作、无扭曲）

---

## 六、GitHub 与隐私

- 仓库：`https://github.com/zhaosenlin12-creator/yxz-3d.git`（分支 `main`）
- ⚠️ **不入 GitHub**（.gitignore 已强制排除）：`keys.txt`、`software_paths.json`、`.glb/.obj/.stl` 大模型文件
- 克隆仓库后需从原电脑拷贝 `cartoon-print-studio\keys.txt`；角色大模型随 ZIP 交付
- 提交前检查：`git status` 出现 `keys.txt` 即禁止 `git add`；勿删除根 `.gitignore` 中的 `**/keys.txt` 规则

## 七、大模型 / 运行数据（不入 GitHub）

| 资源 | 位置 | 说明 |
|---|---|---|
| 角色 3D 模型 | `cartoon-print-studio\data\yxz_character_tripo_jpg\model` | 宜小智角色主模型，ZIP 自带 |
| API keys | `cartoon-print-studio\keys.txt` | 随 ZIP；克隆后需手动放入 |
| 名片模板 | `cartoon-print-studio\data\laser\template\activity_blue.png` | 已入 GitHub |
| 软件路径修正 | `cartoon-print-studio\data\software_paths.json` | 每台机器自动检测生成，不入库 |
