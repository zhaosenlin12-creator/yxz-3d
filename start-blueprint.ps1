# Blueprint 智造工作台独立启动（并入宜小智时由桌面启动器统一拉起）
param(
    [int]$BlueprintPort = 9418,
    [int]$YxzPort = 8100,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $root 'blueprint\server\server.mjs'
if (-not (Test-Path -LiteralPath $server)) { throw "找不到 blueprint\server\server.mjs" }

$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $node) { throw "找不到 Node.js，请先安装 Node 18+" }

# 复用宜小智的 keys.txt，让新克隆不配置也能直接对话/生成
$keys = Join-Path $root 'cartoon-print-studio\keys.txt'
if (Test-Path -LiteralPath $keys) {
    $line = Select-String -LiteralPath $keys -Pattern '^deepseek-key\s*[:=]' | Select-Object -First 1
    if ($line) {
        $env:BLUEPRINT_LLM_PROVIDER = 'deepseek'
        $env:BLUEPRINT_LLM_API_KEY = ($line.Line -split '[:=]', 2)[1].Trim()
        $env:BLUEPRINT_LLM_BASE_URL = 'https://api.deepseek.com/v1'
        $env:BLUEPRINT_LLM_MODEL = 'deepseek-chat'
    }
}

$env:BLUEPRINT_PORT = "$BlueprintPort"
$env:YXZ_PORT = "$YxzPort"
$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null
$out = Join-Path $run "blueprint-$BlueprintPort.out.log"
$err = Join-Path $run "blueprint-$BlueprintPort.err.log"
$pidFile = Join-Path $run 'blueprint.pid'

$tcp = New-Object System.Net.Sockets.TcpClient
try { $tcp.Connect('127.0.0.1', $BlueprintPort); $tcp.Close(); Write-Host "Blueprint 已在运行：http://127.0.0.1:$BlueprintPort/studio" -ForegroundColor Green; if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$BlueprintPort/studio" }; exit 0 } catch {}

$p = Start-Process -FilePath $node -ArgumentList @($server) -WorkingDirectory (Join-Path $root 'blueprint\server') -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $pidFile -Value $p.Id -Encoding ascii

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$BlueprintPort/api/config-status" -TimeoutSec 2
        if ($r.ok) { $ready = $true; break }
    } catch {}
}
if (-not $ready) {
    Write-Host "Blueprint 启动超时，查看日志：$err" -ForegroundColor Red
    Get-Content -LiteralPath $err -Tail 20
    exit 1
}

Write-Host "Blueprint 已启动：http://127.0.0.1:$BlueprintPort/studio" -ForegroundColor Green
Write-Host "3D 后端：http://127.0.0.1:$YxzPort" -ForegroundColor DarkGray
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$BlueprintPort/studio" }
