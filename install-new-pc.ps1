# =====================================================================
#  宜小智工作台 —— 新电脑安装（极速版）
#
#  相对旧版解决的“慢”问题：
#    1. 依赖解析从 pip 换成 uv
#       旧：pip 解析 backend-requirements.txt 在 aiohttp 上指数级回溯，
#           实测 10 分钟仍未收敛（已复现）。
#       新：uv 解析同一份文件 5 秒出结果，下载并行 + 断点续传。
#    2. torch 不再走 pip 下载
#       旧：pip 从 download.pytorch.org 下 2.4GB 会长时间零字节卡死。
#       新：用 .NET HttpWebRequest 先落到本地 wheel 缓存（可跨版本复用），
#           安装时 uv 直接从本地文件装，全程零网络。
#    3. 断点续装：requirements / python 版本 / torch 通道都没变就直接跳过
#    4. 缓存目录可指定（YXZ_CACHE_DIR），换机器把缓存目录拷过去即可秒装
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-new-pc.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-new-pc.ps1 -CpuOnly
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-new-pc.ps1 -Force
# =====================================================================
param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SlowNetwork,               # 不用国内镜像
    [switch]$CpuOnly,                   # 装 CPU 版 torch（无 NVIDIA 显卡时用，体积小 ~10 倍）
    [switch]$Force,                     # 忽略缓存哨兵强制重装
    [switch]$SkipModels,                # 不下载 AI 模型权重（SD 1.5 / Hunyuan3D / TripoSR）
    [switch]$OnlyModels,                # 只下载 AI 模型权重
    [string]$KeysSource = '',           # 一份填好的 keys.txt，直接装到这台机器
    [string]$PypiIndex = 'https://pypi.tuna.tsinghua.edu.cn/simple',
    [string]$NpmRegistry = 'https://registry.npmmirror.com'
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  宜小智工作台 安装（极速版）" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---- 0) 前提检查 -----------------------------------------------------
$node = Get-Command node.exe -ErrorAction SilentlyContinue
$git  = Get-Command git.exe  -ErrorAction SilentlyContinue
if (-not $node) { Fail "未找到 Node.js，请安装 https://nodejs.org （20+）"; exit 1 }
if (-not $git)  { Fail "未找到 Git，请安装 https://git-scm.com"; exit 1 }
Ok "Node.js  $($node.Source)"
Ok "Git     $($git.Source)"

$python = Select-Python
if (-not $python) {
    Fail "未找到 Python 3.10/3.11/3.12，请安装 https://python.org （勾选 Add to PATH）"
    exit 1
}
$pyVer = (& $python -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>$null)
$pyTag = (& $python -c "import sys;print('cp%d%d'%sys.version_info[:2])" 2>$null)
Ok "Python  $python  ($pyVer)"

$uv = Get-UvPath
if ($uv) { Ok "uv      $uv  (依赖解析走 uv，比 pip 快一个数量级)" }
else {
    # 新电脑上一般没装 uv。回退到 pip 解析 aiohttp 会指数级回溯，
    # 实测十分钟都不收敛 —— 所以这里直接把它装上（uv 本体只有十几 MB）。
    Warn "未找到 uv，正在自动安装（pip install uv）..."
    & $python -m pip install --upgrade uv 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) {
        # PEP 668 的"外部管理环境"会直接拒绝安装，换个姿势再来一次。
        & $python -m pip install --upgrade --break-system-packages uv 2>&1 |
            Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    $uv = Get-UvPath
    if ($uv) { Ok "uv      $uv" }
    else     { Warn "uv 安装失败，将回退到 pip（会慢很多，建议先装：pip install uv）" }
}

$corepack = Get-Command corepack.cmd -ErrorAction SilentlyContinue
if (-not $corepack) { Warn "未找到 corepack，改用已安装的 pnpm" }
$pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpm -and $corepack) {
    # Node 16.9+ 自带 corepack，pnpm 只是没被启用而已。
    # 新电脑上这几乎是标准情况，脚本自己把它打开就行。
    Step "启用 corepack 以获得 pnpm ..."
    & $corepack.Source enable 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
}
if (-not $pnpm) { Fail "未找到 pnpm，请执行：corepack enable（Node 自带 corepack）"; exit 1 }
Ok "pnpm    $($pnpm.Source)"

# ---- 1) 镜像 ---------------------------------------------------------
if ($SlowNetwork) {
    Warn "使用官方源（速度慢）"
    $PypiIndex = 'https://pypi.org/simple'
    $NpmRegistry = 'https://registry.npmjs.org'
} else {
    Enable-NpmMirror -Registry $NpmRegistry
    Ok "npm 源 -> $NpmRegistry"
}
$torchIndex = if ($CpuOnly) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu121' }

# ---- 2) 后端 ---------------------------------------------------------
$backend = Join-Path $root 'cartoon-print-studio'
$venv    = Join-Path $backend 'ai\forge-webui\venv'
$venvPy  = Join-Path $venv 'Scripts\python.exe'
$req     = Join-Path $root 'backend-requirements.txt'

if ($OnlyModels) {
    Step "仅下载模型模式：跳过后端依赖"
} elseif ($SkipBackend) {
    Step "已跳过后端"
} else {
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Step "创建 Python 虚拟环境 ($pyVer) ..."
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
            Fail "venv 创建失败"; exit 1
        }
        Ok "venv 已创建"
    }
    if (-not $SlowNetwork) { Enable-PipMirror -VenvDir $venv -Index $PypiIndex }

    # --- 变更检测：requirements + python 版本 + torch 通道 ---
    $torchFlavor = if ($CpuOnly) { 'cpu' } else { 'cu121' }
    $depKey = (Get-FileSha256 $req) + '|' + $pyVer + '|' + $torchFlavor
    $depKey = Get-TextSha256 $depKey
    $stamp  = Join-Path $venv '.deps-hash'

    if (-not $Force -and (Test-Path -LiteralPath $stamp) -and (Get-Content -LiteralPath $stamp -Raw).Trim() -eq $depKey) {
        Ok "后端依赖已就绪（跳过安装，约 1 秒）"
    } else {
        # --- 2.1 torch / torchvision：先落到本地 wheel 缓存 ---
        $wheelDir = Get-WheelCacheDir
        $torchVer = '2.5.1'
        $tvVer    = '0.20.1'
        $wheelSpecs = @(
            @{ Name = "torch-$torchVer+$torchFlavor-$pyTag-$pyTag-win_amd64.whl";      Url = "$torchIndex/torch-$torchVer%2B$torchFlavor-$pyTag-$pyTag-win_amd64.whl" },
            @{ Name = "torchvision-$tvVer+$torchFlavor-$pyTag-$pyTag-win_amd64.whl"; Url = "$torchIndex/torchvision-$tvVer%2B$torchFlavor-$pyTag-$pyTag-win_amd64.whl" }
        )
        $wheelPaths = @()
        foreach ($w in $wheelSpecs) {
            $dest = Join-Path $wheelDir $w.Name
            if (-not ((Test-Path -LiteralPath $dest) -and (Get-Item -LiteralPath $dest).Length -gt 50MB)) {
                Step "下载 $($w.Name) （约 2.4GB，走 .NET 直连避免 pip 卡死）..."
                if (-not (Get-RemoteFile -Url $w.Url -OutFile $dest -TimeoutSec 1800)) {
                    Fail "下载失败：$($w.Url)"
                    Fail "可手工下载后放到 $wheelDir 再重跑本脚本"
                    exit 1
                }
            }
            $wheelPaths += $dest
        }
        Ok "torch wheel 已就绪（本地缓存，跨版本复用）"

        # --- 2.2 主体依赖 ---
        Step "安装 torch / torchvision（本地 wheel，零网络）..."
        $rcTorch = Install-Packages -VenvPy $venvPy -Requirement $wheelPaths -IndexUrl $PypiIndex
        if ($rcTorch -ne 0) { Fail "torch 安装失败（uv exit=$rcTorch）"; exit 1 }
        Ok "torch 安装完成"

        Step "安装后端依赖（uv 解析，通常 1-3 分钟）..."
        $reqFiltered = Join-Path $run 'req-install.txt'
        $lines = Get-Content -LiteralPath $req -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*open-clip-torch==' }
        Set-Content -LiteralPath $reqFiltered -Value $lines -Encoding UTF8
        # 注意：这里刻意 *不* 加 --extra-index-url download.pytorch.org。
        # uv 会为每个包去 extra 源查一次索引，该源在国内极慢，会把 1 分钟的
        # 安装拖成十几分钟。torch 已由上面的本地 wheel 装好，
        # `torch==2.5.1+cu121` 这条 pin 会被已安装的发行版直接满足。
        $rc = Install-Packages -VenvPy $venvPy -Requirement @('-r', $reqFiltered) -IndexUrl $PypiIndex
        if ($rc -ne 0) { Fail "依赖安装失败（uv exit=$rc）"; exit 1 }

        # --- 2.3 open-clip-torch：pin protobuf<4，与 onnxruntime/protobuf 冲突，
        #     后端运行期不 import open_clip，因此单独 --no-deps 安装 ---
        Step "安装 open-clip-torch（--no-deps，规避 protobuf 冲突）..."
        Install-Packages -VenvPy $venvPy -Requirement @('open-clip-torch==2.20.0') -NoDeps | Out-Null

        Set-Content -LiteralPath $stamp -Value $depKey -Encoding ASCII
        Ok "后端依赖安装完成"
    }
}

# ---- 2.5) AI 模型权重 -------------------------------------------------
# 仓库里没有这些权重（.gitignore 排除，只随作者 zip 发布）。
# 缺了它们，本地生图 / 本地 3D 生成都走不通，只能靠云端 key。
if (-not $SkipModels) {
    Step "下载 AI 模型权重（SD 1.5 / Hunyuan3D-2 mini / TripoSR，约 9GB，断点续传）..."
    # 目标机器可能只有 Windows PowerShell 5.1，没有 pwsh。
    $psExe = Get-YxzPowerShell
    if ($psExe) {
        & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'fetch-models.ps1')
    }
    else {
        Warn "找不到 PowerShell，跳过模型权重下载（本地生图 / 本地 3D 会不可用，云端 key 仍可出图）"
    }
    Write-Host ""
}

# ---- 3) 前端 ---------------------------------------------------------
if ($OnlyModels) {
    Step "仅下载模型模式：跳过前端依赖"
} elseif ($SkipFrontend) {
    Step "已跳过前端"
} else {
    $airi = Join-Path $root 'airi'
    $stampF = Join-Path $run 'frontend-deps-ok'
    if (-not $Force -and (Test-Path -LiteralPath $stampF)) {
        Ok "前端依赖已就绪（跳过 pnpm install）"
    } else {
        Step "安装前端依赖（pnpm install，只取 stage-web 依赖闭包）..."
        Push-Location $airi
        try {
            & $pnpm.Source install --filter '@proj-airi/stage-web...' --reporter=append-only
            if ($LASTEXITCODE -ne 0) {
                Warn "过滤安装失败，回退到全量安装 ..."
                & $pnpm.Source install --reporter=append-only
            }
        } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Fail "pnpm install 失败"; exit 1 }
        New-Item -ItemType File -Force -Path $stampF | Out-Null
        Ok "前端依赖安装完成"
    }
}

# ---- 4) 静态资源预置 -------------------------------------------------
Step "预置静态资源（VRM / MediaPipe / Live2D）..."
Seed-Assets -Root $root
Ok "静态资源就绪"

# ---- 5) 校验 ---------------------------------------------------------
$key = Join-Path $backend 'keys.txt'

# 密钥不进仓库（仓库是公开的），所以"另一台电脑要一模一样的体验"
# 靠的是把填好的 keys.txt 带过去：-KeysSource 指向那份文件即可，
# 后面三步（前端 .env.local、provider-seed.json、语音链）全部由它生成。
if ($KeysSource) {
    if (-not (Test-Path -LiteralPath $KeysSource)) {
        Fail "找不到密钥文件：$KeysSource"
        exit 1
    }
    Copy-Item -LiteralPath $KeysSource -Destination $key -Force
    Ok "已安装密钥文件：$KeysSource"
}

if (Test-Path -LiteralPath $key) {
    $filled = (Get-Content -LiteralPath $key -Encoding UTF8 | Where-Object {
        $_ -match '^\s*[A-Za-z0-9_]+\s*[:：]\s*\S+' -and $_ -notmatch '^\s*#'
    }).Count
    if ($filled -gt 0) { Ok "keys.txt 已填入 $filled 项 key" }
    else { Warn "keys.txt 存在但未填 key —— AI 功能会走本地兜底" }
} else {
    Warn "缺少 keys.txt：把模板复制一份并填入 key 即可启用 LLM / 生图 / 云端 3D"
    # 模板在仓库里是安全的（不含密钥），克隆后直接复制一份就能填。
    foreach ($tpl in @(
            (Join-Path $root 'cartoon-print-studio\keys.txt.example'),
            (Join-Path $backend 'keys.txt.example'),
            (Join-Path $root 'keys.example.txt')
        )) {
        if (Test-Path -LiteralPath $tpl) {
            Copy-Item -LiteralPath $tpl -Destination $key -Force
            Ok "已从模板生成 keys.txt（填入 key 后重启后端即可启用）"
            break
        }
    }
}

# ---- 6) 生成前端服务商配置 -------------------------------------------
# 前端的对话 / TTS 凭据走 .env.local（不入库），必须由 keys.txt 生成，
# 否则新机器上前端一个服务商都没有 —— 对话和语音讲解都不可用。
$genBootstrap = Join-Path $root 'gen-provider-bootstrap.ps1'
if (Test-Path -LiteralPath $genBootstrap) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $genBootstrap
} else {
    Warn "缺少 gen-provider-bootstrap.ps1，前端可能没有 LLM / TTS 服务商"
}

# provider-seed.json 带着浏览器侧的对话 / TTS 凭据和语音链
#（MiniMax 主 → 本地 Voicebox → Edge 免费兜底），是"换一台电脑还是
# 同一套体验"的关键文件。它同样不入库，必须由 keys.txt 生成。
$seedScript = Join-Path $root 'cartoon-print-studio\scripts\seed_provider_seed.py'
$seedPy = Join-Path $root 'cartoon-print-studio\ai\forge-webui\venv\Scripts\python.exe'
if ((Test-Path -LiteralPath $seedScript) -and (Test-Path -LiteralPath $seedPy)) {
    & $seedPy $seedScript
    if ($LASTEXITCODE -eq 0) { Ok "provider-seed.json 已生成（含语音链）" }
    else { Warn "provider-seed.json 生成失败，前端可能没有服务商" }
}
else {
    Warn "缺少 seed_provider_seed.py 或后端 venv，跳过 provider-seed.json 生成"
}

# ---- 7) 体检 ---------------------------------------------------------
$verify = Join-Path $root 'verify-install.ps1'
if (Test-Path -LiteralPath $verify) {
    Write-Host ""
    & powershell -NoProfile -ExecutionPolicy Bypass -File $verify
}

Write-Host ""
Write-Host "安装完成。下一步：" -ForegroundColor Green
Write-Host "  .\start-all.ps1        （或双击 启动.bat）"
Write-Host "启动后自动打开 http://127.0.0.1:5199"
