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
    [int]$RuntimePort = 6121,
    [int]$VoiceboxPort = 17493,
    [switch]$NoBrowser,
    [switch]$NoFrontend,
    [switch]$NoBackend,
    [switch]$NoServerRuntime,
    [switch]$NoVoicebox,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null

$backendRoot  = Join-Path $root 'cartoon-print-studio'
$frontendRoot = Join-Path $root 'airi\apps\stage-web'
$runtimeRoot  = Join-Path $root 'airi\packages\server-runtime'
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
    if (-not $NoServerRuntime) {
        $tsxBin = Join-Path $root 'airi\node_modules\.bin\tsx.cmd'
        if (-not (Test-Path -LiteralPath $tsxBin)) { $needInstall = $true }
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

# ---- 3.5) 启动 AIRI server-runtime（WS 通道服务）--------------------
# 前端默认连 ws://localhost:6121/ws。少了这个服务，控制台会一直刷
# "WebSocket connection failed"，订阅/通道相关能力也不稳。
$runtimeProc = $null
$rtReady = $NoServerRuntime
if ($NoServerRuntime) {
    Step "已按参数跳过 server-runtime"
} elseif ($existingRt = Find-ProjectServerRuntime -From $RuntimePort -To ($RuntimePort + 10)) {
    $RuntimePort = $existingRt
    $rtReady = $true
    Ok "server-runtime 已在运行（: $RuntimePort），直接复用"
} else {
    $tsx = Join-Path $root 'airi\node_modules\.bin\tsx.cmd'
    if (-not (Test-Path -LiteralPath $tsx)) { Fail "未找到 tsx，请先运行 install-new-pc.ps1"; exit 1 }
    $out = Join-Path $run "runtime-$RuntimePort.out.log"
    $err = Join-Path $run "runtime-$RuntimePort.err.log"
    $prevPort = $env:PORT
    $prevHost = $env:HOST
    $env:PORT = "$RuntimePort"
    # The channel has to be reachable from the other computers on the
    # network, otherwise they can open the workbench but never talk to it.
    $env:HOST = '0.0.0.0'
    Step "启动 server-runtime (: $RuntimePort) ..."
    try {
        $runtimeProc = Start-Process -FilePath $tsx `
            -ArgumentList @('./src/bin/run.js') `
            -WorkingDirectory $runtimeRoot -RedirectStandardOutput $out -RedirectStandardError $err `
            -WindowStyle Hidden -PassThru
    } finally {
        if ($null -eq $prevPort) { Remove-Item Env:PORT -ErrorAction SilentlyContinue }
        else { $env:PORT = $prevPort }
        if ($null -eq $prevHost) { Remove-Item Env:HOST -ErrorAction SilentlyContinue }
        else { $env:HOST = $prevHost }
    }
    Ok "server-runtime 进程 PID=$($runtimeProc.Id)"
}

# ---- 3.6) 启动本地语音包 Voicebox -----------------------------------
# TTS 的第二级是本机的 Voicebox（Qwen CustomVoice）。它是独立仓库，
# 现场如果没起来，宜小智会退回 Edge 免费语音 —— 能说话，但音色不是
# 挑好的那一把。所以这里顺手拉起来：找到了就启动，没找到就跳过。
$voiceboxProc = $null
$vbReady = $NoVoicebox
if ($NoVoicebox) {
    Step "已按参数跳过本地语音包 Voicebox"
} elseif (Test-Port $VoiceboxPort) {
    $vbReady = $true
    Ok "本地语音包已在运行（: $VoiceboxPort），直接复用"
} else {
    $vbCandidates = @(
        $env:YXZ_VOICEBOX_ROOT,
        (Join-Path (Split-Path -Parent $root) 'voicebox'),
        'C:\kaifa_boot\voicebox',
        (Join-Path $env:USERPROFILE 'kaifa_boot\voicebox')
    ) | Where-Object { $_ }
    $vbRoot = $vbCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ '.venv\Scripts\python.exe') } | Select-Object -First 1
    if (-not $vbRoot) {
        Warn "没找到本地语音包 Voicebox，跳过（宜小智会退回 Edge 免费语音）"
    } else {
        $vbPy = Join-Path $vbRoot '.venv\Scripts\python.exe'
        $out = Join-Path $run "voicebox-$VoiceboxPort.out.log"
        $err = Join-Path $run "voicebox-$VoiceboxPort.err.log"
        $prevCors = $env:VOICEBOX_CORS_ORIGINS
        # The frontend proxies /voicebox-api to this port, so the browser
        # never talks to it cross-origin; the allowed origins are only for
        # somebody opening Voicebox's own playground page.
        $env:VOICEBOX_CORS_ORIGINS = "http://127.0.0.1:$FrontendPort,http://localhost:$FrontendPort"
        Step "启动本地语音包 Voicebox (: $VoiceboxPort) ..."
        try {
            $voiceboxProc = Start-Process -FilePath $vbPy `
                -ArgumentList @('-m','backend.main','--host','127.0.0.1','--port',"$VoiceboxPort") `
                -WorkingDirectory $vbRoot -RedirectStandardOutput $out -RedirectStandardError $err `
                -WindowStyle Hidden -PassThru
            Ok "Voicebox 进程 PID=$($voiceboxProc.Id)"
        } catch {
            Warn "Voicebox 启动失败：$($_.Exception.Message)"
        } finally {
            if ($null -eq $prevCors) { Remove-Item Env:VOICEBOX_CORS_ORIGINS -ErrorAction SilentlyContinue }
            else { $env:VOICEBOX_CORS_ORIGINS = $prevCors }
        }
    }
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
if (-not $NoFrontend) {
    # 注意：就绪判定要分两支。以前写成「已经能识别就直接跳过等待」，
    # 结果 feReady 永远留着 False，明明起来了却报「前端未就绪」。
    if (Test-FrontendIdentity "http://127.0.0.1:$FrontendPort") {
        $feReady = $true
        Ok "前端就绪 http://127.0.0.1:$FrontendPort"
    } else {
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
}
if (-not $NoServerRuntime -and -not $rtReady) {
    Step "等待 server-runtime 就绪 ..."
    $rtDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $rtDeadline) {
        if ($runtimeProc -and $runtimeProc.HasExited) { break }
        if (Test-ServerRuntimeIdentity -Port $RuntimePort) { $rtReady = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if ($rtReady) { Ok "server-runtime 就绪 ws://127.0.0.1:$RuntimePort/ws" }
    else {
        Warn "server-runtime 未就绪（WS 通道不可用，主界面仍可使用）"
        $e = Join-Path $run "runtime-$RuntimePort.err.log"
        if (Test-Path -LiteralPath $e) { Get-Content -LiteralPath $e -Tail 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    }
}
if (-not $NoVoicebox -and -not $vbReady) {
    Step "等待本地语音包就绪 ..."
    $vbDeadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $vbDeadline) {
        if ($voiceboxProc -and $voiceboxProc.HasExited) { break }
        if (Test-HttpOk "http://127.0.0.1:$VoiceboxPort/health") { $vbReady = $true; break }
        Start-Sleep -Milliseconds 800
    }
    if ($vbReady) { Ok "本地语音包就绪 http://127.0.0.1:$VoiceboxPort" }
    else {
        # 不阻断：TTS 还有 MiniMax 和 Edge 两级可以接着用。
        Warn "本地语音包未就绪（宜小智会退回 Edge 免费语音）"
        $e = Join-Path $run "voicebox-$VoiceboxPort.err.log"
        if (Test-Path -LiteralPath $e) { Get-Content -LiteralPath $e -Tail 12 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
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
if (-not $NoServerRuntime) {
    if ($rtReady) { Ok "WS通道  ws://127.0.0.1:$RuntimePort/ws" } else { Warn "WS通道  未就绪 (: $RuntimePort)" }
}
if (-not $NoVoicebox) {
    if ($vbReady) { Ok "本地语音  http://127.0.0.1:$VoiceboxPort" } else { Warn "本地语音  未就绪 (: $VoiceboxPort)" }
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
