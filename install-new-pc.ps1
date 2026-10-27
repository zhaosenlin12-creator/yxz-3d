# =====================================================================
#  pingdou-workstation 新电脑安装脚本
#  前提（手动安装）：
#    - Git for Windows
#    - Node.js 20+ 与 corepack（corepack enable）
#    - Python 3.10/3.11（加入 PATH）
#  本脚本会自动：
#    1) airi 前端：pnpm install（monorepo）
#    2) 后端：创建 venv + pip install -r backend-requirements.txt
#    3) 校验 keys.txt 与目录结构，给出启动指引
#  用法： powershell -ExecutionPolicy Bypass -File install-new-pc.ps1
# =====================================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  宜小智工作台 新电脑安装" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---- 0) 前提检查 ----
$node = Get-Command node.exe -ErrorAction SilentlyContinue
$git = Get-Command git.exe -ErrorAction SilentlyContinue
$py = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $node) { Write-Host "[x] 未找到 Node.js，请先安装 https://nodejs.org（20+）" -ForegroundColor Red; exit 1 }
if (-not $git)  { Write-Host "[x] 未找到 Git，请先安装 https://git-scm.com" -ForegroundColor Red; exit 1 }
if (-not $py)   { Write-Host "[x] 未找到 Python，请先安装 https://python.org（3.10/3.11，勾选 Add to PATH）" -ForegroundColor Red; exit 1 }
Write-Host "[ok] node=$($node.Source)" -ForegroundColor Green
Write-Host "[ok] git =$($git.Source)" -ForegroundColor Green
Write-Host "[ok] py  =$($py.Source)" -ForegroundColor Green
$pyVer = (& $py --version 2>&1 | Out-String).Trim()
Write-Host "[ok] $pyVer" -ForegroundColor Green
if ($pyVer -notmatch 'Python 3\.(10|11)\.') {
    Write-Host "[!] 后端 torch(cu121) 目前只支持 Python 3.10/3.11，$pyVer 可能安装失败。" -ForegroundColor Yellow
    Write-Host "    建议安装 Python 3.10/3.11（勾选 Add to PATH）后重跑本脚本。" -ForegroundColor Yellow
}

# ---- 1) 前端依赖 ----
$airi = Join-Path $root 'airi'
if (Test-Path -LiteralPath (Join-Path $airi 'pnpm-workspace.yaml')) {
    Write-Host "[1/3] 安装前端依赖（pnpm install）..." -ForegroundColor Cyan
    $corepack = Get-Command corepack.cmd -ErrorAction SilentlyContinue
    if (-not $corepack) {
        Write-Host "[x] 未找到 corepack，请运行：corepack enable （或 npm i -g corepack）" -ForegroundColor Red
        exit 1
    }
    Push-Location $airi
    try {
        & $corepack.Source pnpm install
        if ($LASTEXITCODE -ne 0) { throw "pnpm install 失败 (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
    Write-Host "[ok] 前端依赖安装完成" -ForegroundColor Green
} else {
    Write-Warning "未找到 airi/pnpm-workspace.yaml，跳过前端安装。"
}

# ---- 2) 后端依赖 ----
$backend = Join-Path $root 'cartoon-print-studio'
$venvPy = Join-Path $backend 'ai\forge-webui\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host "[2/3] 创建后端 Python 虚拟环境 ..." -ForegroundColor Cyan
    & $py -m venv (Join-Path $backend 'ai\forge-webui\venv')
    if ($LASTEXITCODE -ne 0) { Write-Host "[x] venv 创建失败" -ForegroundColor Red; exit 1 }
}
$req = Join-Path $root 'backend-requirements.txt'
if (Test-Path -LiteralPath $req) {
    Write-Host "[2b/3] 安装后端依赖（约几分钟，torch 较大）..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    # torch/torchvision 的 +cu121 版本来自 PyTorch 官方索引，标准 PyPI 上没有
    & $venvPy -m pip install -r $req --extra-index-url https://download.pytorch.org/whl/cu121
    if ($LASTEXITCODE -ne 0) { Write-Host "[x] pip install 失败，请重试" -ForegroundColor Red; exit 1 }
    Write-Host "[ok] 后端依赖安装完成" -ForegroundColor Green
} else {
    Write-Warning "未找到 backend-requirements.txt，跳过后端依赖安装。"
}

# ---- 3) 校验与提示 ----
$key = Join-Path $backend 'keys.txt'
if (Test-Path -LiteralPath $key) {
    Write-Host "[ok] keys.txt 存在（API key 配置完整）" -ForegroundColor Green
} else {
    Write-Host "[!] keys.txt 缺失！请从原电脑拷贝（含 minimax/deepseek/aixj 等标签的 key 文件）到 $backend" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "安装完成。下一步运行：" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File start-all.ps1"
Write-Host "启动后自动打开 http://127.0.0.1:5199"
