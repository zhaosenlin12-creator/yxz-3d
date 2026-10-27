# =====================================================================
#  pingdou-workstation 一键启动
#  启动顺序：
#    1) cartoon-print-studio 后端（FastAPI :8000，自动读 keys.txt）
#    2) airi 前端（vite :5199，VITE_CARTOON_PRINT_API=http://127.0.0.1:8000）
#    3) 就绪后自动打开浏览器
#  失败兜底：端口占用 / venv 缺失 / node 缺失 都会给出明确提示。
#  用法： powershell -ExecutionPolicy Bypass -File start-all.ps1
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [switch]$NoBrowser,
    [switch]$NoFrontend,
    [string]$BackendRoot = "",
    [string]$FrontendRoot = ""
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BackendRoot)  { $BackendRoot  = Join-Path $root 'cartoon-print-studio' }
if (-not $FrontendRoot) { $FrontendRoot = Join-Path $root 'airi' }

function Test-Port([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
}

function Find-ViteBin {
    $vite = Get-ChildItem -LiteralPath (Join-Path $frontendRoot 'node_modules\.pnpm') -Recurse -Filter 'vite.js' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'vite@8' -and $_.FullName -match '\\bin\\vite\.js$' } |
        Select-Object -First 1
    if ($vite) { return $vite.FullName }
    $corepack = Get-Command 'corepack.cmd' -ErrorAction SilentlyContinue
    if ($corepack) { return 'corepack' }
    return $null
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  宜小智工作台 一键启动" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---- 0) 依赖预检（每步显式 OK / FAIL） ----
function Step-Ok([string]$Label) { Write-Host ("  [OK]   " + $Label) -ForegroundColor Green }
function Step-Fail([string]$Label) { Write-Host ("  [FAIL] " + $Label) -ForegroundColor Red }
function Step-Info([string]$Label) { Write-Host ("  [..]   " + $Label) -ForegroundColor Cyan }
function Show-Spinner([int]$DurationSec) {
    $chars = '|/-\'
    $end = (Get-Date).AddSeconds($DurationSec)
    $i = 0
    while ((Get-Date) -lt $end) {
        Write-Host ("`r  等待中 " + $chars[$i % 4] + " ") -NoNewline
        $i++
        Start-Sleep -Milliseconds 220
    }
    Write-Host "`r                        " -NoNewline
}

Step-Info "预检依赖 ..."
$nodeBin = Get-Command node.exe -ErrorAction SilentlyContinue
$corepackBin = Get-Command corepack.cmd -ErrorAction SilentlyContinue
if ($nodeBin) { Step-Ok "Node.js: $($nodeBin.Source)" } else { Step-Fail "未找到 Node.js（前端无法启动）" }
if ($corepackBin) { Step-Ok "corepack 可用" } else { Step-Info "corepack 未启用（将尝试直接找 vite）" }

# ---- 1) 后端 ----
$py = Join-Path $backendRoot 'ai\forge-webui\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host ""
    Write-Host "[后端] 未找到 Python 虚拟环境（venv）。" -ForegroundColor Yellow
    Write-Host "[后端] 首次使用需要先安装后端依赖（torch 等约 2GB，需联网，预计 10-30 分钟）。" -ForegroundColor Yellow
    Write-Host "[后端] 现在自动执行安装脚本 install-new-pc.ps1（请勿关闭窗口，耐心等待）..." -ForegroundColor Yellow
    Write-Host ""
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'install-new-pc.ps1')
    if (-not (Test-Path -LiteralPath $py)) {
        Write-Host "[后端] 自动安装未完成。" -ForegroundColor Red
        Write-Host "[后端] 请手动运行 install-new-pc.ps1（或重新双击 一键安装并启动.bat）后重试；详见 README.md「详细手动步骤」。" -ForegroundColor Red
        exit 1
    }
    Write-Host "[后端] 依赖安装完成，继续启动 ..." -ForegroundColor Green
}
if (Test-Port $BackendPort) {
    Write-Host "[后端] 端口 $BackendPort 已被占用（跳过启动）。请确认它确实是本项目的后端。" -ForegroundColor Yellow
} else {
    $out = Join-Path $root ".run\backend-$BackendPort.out.log"
    $err = Join-Path $root ".run\backend-$BackendPort.err.log"
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    $be = Start-Process -FilePath $py -ArgumentList @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', "$BackendPort", '--app-dir', 'backend') `
        -WorkingDirectory $backendRoot -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    Write-Host "[后端] 启动中 PID=$($be.Id) (日志: $out)" -ForegroundColor Green
}
Write-Host "[后端] 等待就绪 ..." -ForegroundColor Cyan
Show-Spinner 2
$beReady = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-Port $BackendPort) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/software/detect" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $beReady = $true; break }
        } catch {}
    }
    Start-Sleep -Seconds 1
}
if ($beReady) {
    Write-Host "[后端] 就绪：http://127.0.0.1:$BackendPort  (API keys 已自动读取 keys.txt)" -ForegroundColor Green
    Step-Ok "后端服务 ($BackendPort) 启动成功"
} else {
    Write-Host "[后端] 等待超时，检查 .run\backend-$BackendPort.err.log。" -ForegroundColor Red
    Step-Fail "后端服务 ($BackendPort) 未就绪"
    if (Test-Path -LiteralPath (Join-Path $root ".run\backend-$BackendPort.err.log")) {
        Get-Content -LiteralPath (Join-Path $root ".run\backend-$BackendPort.err.log") -Tail 20
    }
}

# ---- 2) 前端 ----
if (-not $NoFrontend) {
    if (Test-Port $FrontendPort) {
        Write-Host "[前端] 端口 $FrontendPort 已被占用（跳过启动）。若页面异常请先关闭旧实例。" -ForegroundColor Yellow
    } else {
        $vite = Find-ViteBin
        if (-not $vite) {
            Write-Host ""
            Write-Host "[前端] 未找到 vite（前端依赖未安装），自动执行安装脚本 install-new-pc.ps1 ..." -ForegroundColor Yellow
            Write-Host "[前端] 前端依赖约数百 MB，需联网，请耐心等待。" -ForegroundColor Yellow
            Write-Host ""
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'install-new-pc.ps1')
            $vite = Find-ViteBin
            if (-not $vite) {
                Write-Host "[前端] 自动安装未完成，请手动运行 install-new-pc.ps1 后重试。" -ForegroundColor Red
                exit 1
            }
        }
        $out = Join-Path $root ".run\frontend-$FrontendPort.out.log"
        $err = Join-Path $root ".run\frontend-$FrontendPort.err.log"
        New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
        $env:VITE_CARTOON_PRINT_API = "http://127.0.0.1:$BackendPort"
        if ($vite -eq 'corepack') {
            $fe = Start-Process -FilePath (Get-Command 'corepack.cmd' -ErrorAction Stop).Source -ArgumentList @('pnpm', 'exec', 'vite', '--host', '--port', "$FrontendPort") `
                -WorkingDirectory (Join-Path $frontendRoot 'apps\stage-web') -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
        } else {
            $fe = Start-Process -FilePath (Get-Command 'node.exe' -ErrorAction Stop).Source -ArgumentList @($vite, '--host', '--port', "$FrontendPort") `
                -WorkingDirectory (Join-Path $frontendRoot 'apps\stage-web') -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
        }
        Write-Host "[前端] 启动中 PID=$($fe.Id) (日志: $out)" -ForegroundColor Green
    }
    $feReady = $false
    for ($i = 0; $i -lt 90; $i++) {
        if (Test-Port $FrontendPort) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" -TimeoutSec 3 -UseBasicParsing
                if ($r.StatusCode -eq 200) { $feReady = $true; break }
            } catch {}
        }
        Start-Sleep -Seconds 1
    }
    if ($feReady) {
        Write-Host "[前端] 就绪：http://127.0.0.1:$FrontendPort" -ForegroundColor Green
        Step-Ok "前端服务 ($FrontendPort) 启动成功"
        if (-not $NoBrowser) {
            Start-Process "http://127.0.0.1:$FrontendPort/"
        }
    } else {
        Write-Host "[前端] 等待超时（首次冷编译可能较慢），查看 .run\frontend-$FrontendPort.err.log。" -ForegroundColor Red
        Step-Fail "前端服务 ($FrontendPort) 未就绪"
        if (Test-Path -LiteralPath (Join-Path $root ".run\frontend-$FrontendPort.err.log")) {
            Get-Content -LiteralPath (Join-Path $root ".run\frontend-$FrontendPort.err.log") -Tail 20
        }
    }
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  启动结果汇总" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
if (Test-Port $BackendPort) {
    Step-Ok "后端  http://127.0.0.1:$BackendPort"
} else {
    Step-Fail "后端 未监听 :$BackendPort"
}
if (-not $NoFrontend -and (Test-Port $FrontendPort)) {
    Step-Ok "前端  http://127.0.0.1:$FrontendPort"
} elseif ($NoFrontend) {
    Step-Info "前端 已按参数跳过（-NoFrontend）"
} else {
    Step-Fail "前端 未监听 :$FrontendPort"
}
Write-Host ""
