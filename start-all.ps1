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

$ErrorActionPreference = 'Stop'
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

# ---- 1) 后端 ----
$py = Join-Path $backendRoot 'ai\forge-webui\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[后端] 未找到 venv：$py" -ForegroundColor Red
    Write-Host "[后端] 请先运行 install-new-pc.ps1 创建 Python 环境。" -ForegroundColor Yellow
    exit 1
}
if (Test-Port $BackendPort) {
    Write-Host "[后端] 端口 $BackendPort 已被占用（跳过启动）。请确认它确实是本项目的后端。" -ForegroundColor Yellow
} else {
    $out = Join-Path $root '.run\backend-$BackendPort.out.log'
    $err = Join-Path $root '.run\backend-$BackendPort.err.log'
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    $be = Start-Process -FilePath $py -ArgumentList @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', "$BackendPort", '--app-dir', 'backend') `
        -WorkingDirectory $backendRoot -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    Write-Host "[后端] 启动中 PID=$($be.Id) (日志: $out)" -ForegroundColor Green
}
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
} else {
    Write-Host "[后端] 等待超时，检查 .run\backend-*.err.log。" -ForegroundColor Red
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
            Write-Host "[前端] 未找到 vite / corepack，请先运行 install-new-pc.ps1 安装前端依赖。" -ForegroundColor Red
            exit 1
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
        if (-not $NoBrowser) {
            Start-Process "http://127.0.0.1:$FrontendPort/"
        }
    } else {
        Write-Host "[前端] 等待超时（首次冷编译可能较慢），查看 .run\frontend-*.err.log。" -ForegroundColor Red
        if (Test-Path -LiteralPath (Join-Path $root ".run\frontend-$FrontendPort.err.log")) {
            Get-Content -LiteralPath (Join-Path $root ".run\frontend-$FrontendPort.err.log") -Tail 20
        }
    }
}

Write-Host ""
Write-Host "完成。前端 http://127.0.0.1:$FrontendPort ，后端 http://127.0.0.1:$BackendPort" -ForegroundColor Cyan
