# Start Cartoon Print Studio backend.
param(
    [int]$Port = 8000,
    [switch]$Wait,
    [string]$Python
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_OFFLINE = "0"
$env:PYTHONUNBUFFERED = "1"
$env:SCENE_TRAINER_MODE = "local"
$env:SCENE_BRUSH_BIN = (Join-Path $root "tools\brush\app\brush_app.exe")
$env:SCENE_COLMAP_BIN = (Join-Path $root "tools\colmap\app\COLMAP.bat")
$env:SCENE_BRUSH_STEPS = "3000"
$env:SCENE_MIN_REGISTERED_IMAGES = "8"
$env:CARTOON_ROOT = $root
$env:CARTOON_FRONTEND_DIR = (Join-Path $root "frontend")
$env:CARTOON_DATA_DIR = (Join-Path $root "data")
$log = Join-Path $root "logs\backend.log"
$pidFile = Join-Path $root "logs\backend.pid"
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

function Test-PortFree([int]$PortNumber) {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $PortNumber)
    try {
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Test-OurBackend([int]$PortNumber) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$PortNumber/api/health"
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# A pid file from a previous run is only useful while that process is alive.
if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -Raw).Trim()
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "[backend] already running (pid=$oldPid). Run scripts\stop_backend.ps1 to stop it."
        exit 0
    }
    Remove-Item $pidFile -Force
    Write-Host "[backend] removed stale pid file"
}

if (-not (Test-PortFree $Port)) {
    if (Test-OurBackend $Port) {
        Write-Host "[backend] Cartoon Print Studio is already serving on port $Port"
        exit 0
    }
    Write-Host "[backend] port $Port is used by another program."
    Write-Host "[backend] close it, or start on another port: scripts\start_backend.ps1 -Port 8010"
    exit 1
}

Set-Location (Join-Path $root "ai\forge-webui")
$exe = $Python
if (-not $exe) {
    $exe = Join-Path $root "ai\forge-webui\venv\Scripts\python.exe"
}
if (-not $exe -or -not (Test-Path $exe)) {
    # A checkout without its own virtualenv can point at one elsewhere.
    if ($env:CARTOON_VENV -and (Test-Path $env:CARTOON_VENV)) {
        $exe = $env:CARTOON_VENV
    } else {
        $exe = "python"
        Write-Host "[backend] virtualenv not found, falling back to the system python"
    }
}
$args = @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "$Port", "--app-dir", (Join-Path $root "backend"))
$proc = Start-Process -FilePath $exe -ArgumentList $args -PassThru -NoNewWindow `
    -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root "logs\backend-err.log")
Set-Content -Path $pidFile -Value $proc.Id
Write-Host "[backend] pid=$($proc.Id) port=$Port log=$log"

if ($Wait) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Test-OurBackend $Port) {
            Write-Host "[backend] ready on http://127.0.0.1:$Port"
            exit 0
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "[backend] did not become healthy within 60s, see $log"
    exit 1
}
