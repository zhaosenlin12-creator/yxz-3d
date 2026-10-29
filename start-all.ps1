# =====================================================================
#  宜小智工作台 —— 一键启动
#
#  针对“用起来太麻烦”的优化：
#    1. 端口自动腾挪：8000 被别的程序占用时自动顺延到 8001/8002，
#       并把真实端口注入前端（VITE_CARTOON_PRINT_API）
#    2. 已在运行就直接复用，不重复拉起
#    3. 依赖自检 → 缺失时自动调 install-new-pc.ps1（带断点续装）
#    4. 失败自动打印日志尾部 + 常见原因提示，不用去翻文件
#    5. 默认带守护进程 supervise-all.ps1：后端崩了会自动拉起来，
#       不用再手动重启整套东西
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1 -NoBrowser
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1 -NoBackend
#    powershell -NoProfile -ExecutionPolicy Bypass -File start-all.ps1 -NoSupervisor
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [int]$RuntimePort = 6121,
    [int]$VoiceboxPort = 17493,
    [switch]$NoBrowser,
    [switch]$NoFrontend,
    [switch]$NoBackend,
    [switch]$NoServerRuntime,
    [switch]$NoVoicebox,
    [switch]$NoSupervisor,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')
. (Join-Path $root 'lib-services.ps1')

$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null
Initialize-YxzRunDir

$backendRoot = Join-Path $root 'cartoon-print-studio'
$frontendRoot = Join-Path $root 'airi\apps\stage-web'
$venvPy = Join-Path $backendRoot 'ai\forge-webui\venv\Scripts\python.exe'

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
    if (-not $NoServerRuntime) {
        $tsxBin = Join-Path $root 'airi\node_modules\.bin\tsx.cmd'
        if (-not (Test-Path -LiteralPath $tsxBin)) { $needInstall = $true }
    }
    if ($needInstall) {
        Write-Host ""
        Warn "检测到依赖缺失，正在自动安装（已装过的部分会跳过）..."
        Write-Host ""
        # 目标机器可能只有 Windows PowerShell 5.1，没有 pwsh。
        $psExe = Get-YxzPowerShell
        if (-not $psExe) { Fail "找不到 PowerShell，无法自动安装依赖"; exit 1 }
        & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'install-new-pc.ps1')
        if ($LASTEXITCODE -ne 0) { Fail "自动安装未完成，请手动运行 install-new-pc.ps1"; exit 1 }
        Write-Host ""
    }
}

# ---- 1) 端口规划 -----------------------------------------------------
# 先全端口扫描：只要本项目的后端还在跑（哪怕在 8001/8002）就直接复用，
# 避免反复双击启动脚本时堆出一串僵尸后端。
if (-not $NoBackend) {
    $existing = Find-ProjectBackend -From 8000 -To 8030
    if ($existing) {
        $BackendPort = $existing
        Ok "后端已在运行（: $BackendPort），直接复用"
    }
    elseif (Test-Port $BackendPort) {
        $free = Get-FreePort -Preferred $BackendPort
        if (-not $free) { Fail "找不到可用后端端口（$BackendPort 起连续 60 个都被占）"; exit 1 }
        Warn "端口 $BackendPort 被其它程序占用，后端改用 $free"
        $BackendPort = $free
    }
}

if (-not $NoFrontend) {
    $existingFront = Find-ProjectFrontend -From 5199 -To 5230
    if ($existingFront) {
        $FrontendPort = $existingFront
        Ok "前端已在运行（: $FrontendPort），直接复用"
    }
    elseif (Test-Port $FrontendPort) {
        $free = Get-FreePort -Preferred $FrontendPort
        if (-not $free) { Fail "找不到可用前端端口"; exit 1 }
        Warn "端口 $FrontendPort 被其它程序占用，前端改用 $free"
        $FrontendPort = $free
    }
}

# ---- 2) 拉起守护进程 -------------------------------------------------
# 守护进程是四个服务的唯一所有者：它负责启动、崩溃重启、卡死检测。
# 这样「手动启动」和「自动拉起」走的是同一条路径，不会出现两套进程
# 抢同一个端口的情况。
$supervisorFile = Join-Path $run 'supervisor.pid'
$supervisorRunning = $false
if (Test-Path -LiteralPath $supervisorFile) {
    $raw = ([System.IO.File]::ReadAllText($supervisorFile)).Trim()
    [int]$oldPid = 0
    if ([int]::TryParse($raw, [ref]$oldPid) -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        $supervisorRunning = $true
        Ok "守护进程已在运行（PID=$oldPid），直接复用"
    }
}

if (-not $supervisorRunning) {
    $supervisorArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'supervise-all.ps1'),
        '-BackendPort', "$BackendPort",
        '-FrontendPort', "$FrontendPort",
        '-RuntimePort', "$RuntimePort",
        '-VoiceboxPort', "$VoiceboxPort"
    )
    if ($NoBackend) { $supervisorArgs += '-SkipBackend' }
    if ($NoFrontend) { $supervisorArgs += '-SkipFrontend' }
    if ($NoServerRuntime) { $supervisorArgs += '-SkipRuntime' }
    if ($NoVoicebox) { $supervisorArgs += '-NoVoicebox' }

    Step "启动守护进程 ..."
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if (-not $pwsh) { $pwsh = Get-Command powershell -ErrorAction Stop }
    # 用脱离式启动：守护进程不属于本脚本的进程组，脚本退出、控制台
    # 关闭、或者有人按进程组批量结束，都不会把四个服务一起带走。
    $supervisorPid = Start-YxzDetachedProcess -FilePath $pwsh.Source `
        -Arguments $supervisorArgs -WorkingDirectory $root
    if ($supervisorPid -gt 0) {
        [System.IO.File]::WriteAllText($supervisorFile, [string]$supervisorPid)
        Ok "守护进程 PID=$supervisorPid"
    }
    else {
        Fail "守护进程启动失败，请看 $run\supervisor.log"
    }
}

# ---- 3) 等待就绪 -----------------------------------------------------
function Wait-YxzReady {
    param([string]$Label, [scriptblock]$Test, [int]$TimeoutSec, [string]$LogHint)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (& $Test) { return $true }
        Start-Sleep -Milliseconds 600
    }
    if ($LogHint -and (Test-Path -LiteralPath $LogHint)) {
        Get-Content -LiteralPath $LogHint -Tail 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    return $false
}

# 每个服务每次启动一个日志文件，失败时把最新那一份的尾巴打出来。
function Get-YxzLogHint {
    param([string]$Name, [int]$Port)
    $latest = Get-YxzLatestLog -Name $Name -Port $Port
    if ($latest -and (Test-Path -LiteralPath $latest.Err)) { return $latest.Err }
    return ''
}

$beReady = $NoBackend
$feReady = $NoFrontend
$rtReady = $NoServerRuntime
$vbReady = $NoVoicebox

if (-not $NoBackend) {
    Step "等待后端就绪 ..."
    $beReady = Wait-YxzReady -Label '后端' -Test { Test-YxzBackendReady -Port $BackendPort } `
        -TimeoutSec 120 -LogHint (Get-YxzLogHint -Name 'backend' -Port $BackendPort)
    if ($beReady) { Ok "后端就绪 http://127.0.0.1:$BackendPort" }
    else { Fail "后端未就绪" }
}
if (-not $NoFrontend) {
    Step "等待前端就绪（首次冷编译约 20-60 秒）..."
    $feReady = Wait-YxzReady -Label '前端' -Test { Test-YxzFrontendReady -Port $FrontendPort } `
        -TimeoutSec 180 -LogHint (Get-YxzLogHint -Name 'frontend' -Port $FrontendPort)
    if ($feReady) { Ok "前端就绪 http://127.0.0.1:$FrontendPort" }
    else { Fail "前端未就绪" }
}
if (-not $NoServerRuntime) {
    Step "等待 server-runtime 就绪 ..."
    $rtReady = Wait-YxzReady -Label 'WS通道' -Test { Test-YxzRuntimeReady -Port $RuntimePort } `
        -TimeoutSec 90 -LogHint (Get-YxzLogHint -Name 'runtime' -Port $RuntimePort)
    if ($rtReady) { Ok "server-runtime 就绪 ws://127.0.0.1:$RuntimePort/ws" }
    else { Warn "server-runtime 未就绪（WS 通道不可用，主界面仍可使用）" }
}
if (-not $NoVoicebox) {
    Step "等待本地语音包就绪 ..."
    $vbReady = Wait-YxzReady -Label '本地语音包' -Test { Test-YxzVoiceboxReady -Port $VoiceboxPort } `
        -TimeoutSec 180 -LogHint (Get-YxzLogHint -Name 'voicebox' -Port $VoiceboxPort)
    if ($vbReady) { Ok "本地语音包就绪 http://127.0.0.1:$VoiceboxPort" }
    else { Warn "本地语音包未就绪（宜小智会退回 Edge 免费语音）" }
}

# ---- 4) 汇总 + 自动开浏览器 -----------------------------------------
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
if (-not $NoServerRuntime) {
    if ($rtReady) { Ok "WS通道  ws://127.0.0.1:$RuntimePort/ws" } else { Warn "WS通道  未就绪 (: $RuntimePort)" }
}
if (-not $NoVoicebox) {
    if ($vbReady) { Ok "本地语音  http://127.0.0.1:$VoiceboxPort" } else { Warn "本地语音  未就绪 (: $VoiceboxPort)" }
}
$elapsed = [int]((Get-Date) - $startAt).TotalSeconds
Say "  用时 ${elapsed}s" 'DarkGray'

if ($feReady -and -not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort/"
    Ok "已打开浏览器"
}
Write-Host ""
Say "  日志：$run" 'DarkGray'
Say "  守护进程会在后台自动拉起崩溃的服务" 'DarkGray'
Say "  停止：.\stop-all.ps1" 'DarkGray'
Write-Host ""





