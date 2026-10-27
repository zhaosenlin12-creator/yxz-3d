# =====================================================================
#  宜小智工作台 —— 一键启动
#
#  针对“用起来太麻烦”的优化：
#    1. 前后端并行启动 + 并行等待就绪（不是串行等两个）
#    2. 端口自动腾挪：8000 被别的程序占用时自动顺延到 8001/8002，
#       并把真实端口注入前端（VITE_CARTOON_PRINT_API）
#    3. 已在运行就直接复用，不重复拉起
#    4. 依赖自检 → 缺失时自动调 install-new-pc.ps1（带断点续装）
#    5. 失败自动打印日志尾部 + 常见原因提示，不用去翻文件
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1 -NoBrowser
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1 -NoBackend
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [switch]$NoBrowser,
    [switch]$NoFrontend,
    [switch]$NoBackend,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null

$backendRoot  = Join-Path $root 'cartoon-print-studio'
$frontendRoot = Join-Path $root 'airi\apps\stage-web'
$venvPy       = Join-Path $backendRoot 'ai\forge-webui\venv\Scripts\python.exe'

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  宜小智工作台 启动" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

$startAt = Get-Date

# ---- 0) 依赖自检 -----------------------------------------------------
if (-not $SkipInstall) {
    $needInstall = $false
    if (-not $NoBackend -and -not (Test-Path -LiteralPath $venvPy)) { $needInstall = $true }
    if (-not $NoFrontend) {
        $vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
        if (-not (Test-Path -LiteralPath $vite)) { $needInstall = $true }
    }
    if ($needInstall) {
        Write-Host ""
        Warn "检测到依赖缺失，正在自动安装（已装过的部分会跳过）..."
        Write-Host ""
        & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'install-new-pc.ps1')
        if ($LASTEXITCODE -ne 0) { Fail "自动安装未完成，请手动运行 install-new-pc.ps1"; exit 1 }
        Write-Host ""
    }
}

# ---- 1) 端口规划 -----------------------------------------------------
# 先全端口扫描：只要本项目的后端还在跑（哪怕在 8001/8002）就直接复用，
# 避免反复双击启动脚本时堆出一串僵尸后端。
$backendReuse = $false
$beReady = $NoBackend
$feReady = $NoFrontend
if (-not $NoBackend) {
    $existing = Find-ProjectBackend -From 8000 -To 8030
    if ($existing) {
        $BackendPort = $existing
        $backendReuse = $true
        Ok "后端已在运行（: $BackendPort），直接复用"
    } elseif (Test-Port $BackendPort) {
        $free = Get-FreePort -Preferred $BackendPort
        if (-not $free) { Fail "找不到可用后端端口（$BackendPort 起连续 60 个都被占）"; exit 1 }
        Warn "端口 $BackendPort 被其它程序占用，后端改用 $free"
        $BackendPort = $free
    }
}

# ---- 2) 启动后端 -----------------------------------------------------
$backendProc = $null
if ($NoBackend) {
    Step "已按参数跳过后端"
} elseif ($backendReuse) {
    Step "复用已运行的后端"
    $beReady = $true
} else {
    if (-not (Test-Path -LiteralPath $venvPy)) { Fail "后端 venv 不存在，请先运行 install-new-pc.ps1"; exit 1 }
    $out = Join-Path $run "backend-$BackendPort.out.log"
    $err = Join-Path $run "backend-$BackendPort.err.log"
    Step "启动后端 (: $BackendPort) ..."
    $backendProc = Start-Process -FilePath $venvPy `
        -ArgumentList @('-m','uvicorn','server:app','--host','127.0.0.1','--port',"$BackendPort",'--app-dir','backend') `
        -WorkingDirectory $backendRoot -RedirectStandardOutput $out -RedirectStandardError $err `
        -WindowStyle Hidden -PassThru
    Ok "后端进程 PID=$($backendProc.Id)"
}

# ---- 3) 启动前端（与后端并行）---------------------------------------
$frontendProc = $null
if ($NoFrontend) {
    Step "已按参数跳过前端"
} elseif ($existingFront = Find-ProjectFrontend -From 5199 -To 5230) {
    $FrontendPort = $existingFront
    Ok "前端已在运行（: $FrontendPort），直接复用"
    $feReady = $true
} elseif (Test-Port $FrontendPort) {
    $free = Get-FreePort -Preferred $FrontendPort
    if (-not $free) { Fail "找不到可用前端端口"; exit 1 }
    Warn "端口 $FrontendPort 被其它程序占用，前端改用 $free"
    $FrontendPort = $free
} else {
    $vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $vite)) { Fail "未找到 vite，请先运行 install-new-pc.ps1"; exit 1 }
    # 前端的 LLM / TTS 凭据靠 .env.local 注入，而 .env.local 是由
    # cartoon-print-studio\keys.txt 生成的（不入库）。每次启动都重新生成，
    # 这样换机器、换 key 之后不需要再手动去设置页填一遍。
    $genBootstrap = Join-Path $root 'gen-provider-bootstrap.ps1'
    if (Test-Path -LiteralPath $genBootstrap) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $genBootstrap | Out-Null
    }
    $out = Join-Path $run "frontend-$FrontendPort.out.log"
    $err = Join-Path $run "frontend-$FrontendPort.err.log"
    $env:VITE_CARTOON_PRINT_API = "http://127.0.0.1:$BackendPort"
    Step "启动前端 (: $FrontendPort) ..."
    $frontendProc = Start-Process -FilePath (Get-Command node.exe -ErrorAction Stop).Source `
        -ArgumentList @($vite,'--host','--port',"$FrontendPort") `
        -WorkingDirectory $frontendRoot -RedirectStandardOutput $out -RedirectStandardError $err `
        -WindowStyle Hidden -PassThru
    Ok "前端进程 PID=$($frontendProc.Id)"
}

# ---- 4) 并行等待就绪（一个循环同时盯两个）---------------------------
$beDeadline = (Get-Date).AddSeconds(120)
$feDeadline = (Get-Date).AddSeconds(180)

if (-not $NoBackend -and -not $backendReuse) {
    Step "等待后端就绪 ..."
    while ((Get-Date) -lt $beDeadline) {
        if ($backendProc -and $backendProc.HasExited) { break }
        if (Test-HttpOk "http://127.0.0.1:$BackendPort/api/software/detect") { $beReady = $true; break }
        Start-Sleep -Milliseconds 600
    }
    if ($beReady) { Ok "后端就绪 http://127.0.0.1:$BackendPort" }
    else {
        Fail "后端未就绪"
        $e = Join-Path $run "backend-$BackendPort.err.log"
        if (Test-Path -LiteralPath $e) { Get-Content -LiteralPath $e -Tail 25 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    }
}
if (-not $NoFrontend -and -not (Test-FrontendIdentity "http://127.0.0.1:$FrontendPort")) {
    Step "等待前端就绪（首次冷编译约 20-60 秒）..."
    while ((Get-Date) -lt $feDeadline) {
        if ($frontendProc -and $frontendProc.HasExited) { break }
        if (Test-HttpOk "http://127.0.0.1:$FrontendPort/") { $feReady = $true; break }
        Start-Sleep -Milliseconds 600
    }
    if ($feReady) { Ok "前端就绪 http://127.0.0.1:$FrontendPort" }
    else {
        Fail "前端未就绪"
        $e = Join-Path $run "frontend-$FrontendPort.err.log"
        if (Test-Path -LiteralPath $e) { Get-Content -LiteralPath $e -Tail 25 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    }
}

# ---- 5) 汇总 + 自动开浏览器 -----------------------------------------
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  启动结果" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
if (-not $NoBackend) {
    if ($beReady) { Ok "后端  http://127.0.0.1:$BackendPort" } else { Fail "后端 未就绪 (: $BackendPort)" }
}
if (-not $NoFrontend) {
    if ($feReady) { Ok "前端  http://127.0.0.1:$FrontendPort" } else { Fail "前端 未就绪 (: $FrontendPort)" }
}
$elapsed = [int]((Get-Date) - $startAt).TotalSeconds
Say  "  用时 ${elapsed}s" 'DarkGray'

if ($feReady -and -not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort/"
    Ok "已打开浏览器"
}
Write-Host ""
Say  "  日志：$run" 'DarkGray'
Say  "  停止：.\stop-all.ps1" 'DarkGray'
Write-Host ""
