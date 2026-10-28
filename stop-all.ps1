# =====================================================================
#  宜小智工作台 —— 停止全部服务
#
#  做三件事：
#    1. 先停守护进程（supervise-all.ps1），别让它把服务又拉起来
#    2. 按 PID 文件把四个服务的整棵进程树收掉
#    3. 再扫一遍端口捡漏，最后等端口真正释放
#
#  第 3 步是「停完再启」能成功的关键：以前杀完进程就返回，端口还在
#  TIME_WAIT / 进程还没退，下一次启动直接 bind 失败。
#
#  用法： pwsh -NoProfile -ExecutionPolicy Bypass -File stop-all.ps1
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [int]$RuntimePort = 6121,
    [int]$VoiceboxPort = 17493,
    [switch]$Quiet,
    [int]$OnlyPort = 0
)

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')
. (Join-Path $root 'lib-services.ps1')

Initialize-YxzRunDir

if (-not $Quiet) {
    Write-Host ""
    Write-Host "  宜小智工作台 停止中 ..." -ForegroundColor Cyan
    Write-Host ""
}

$stoppedPorts = New-Object 'System.Collections.Generic.List[int]'

function Note-Port {
    param([int]$Port)
    if ($Port -gt 0 -and -not $stoppedPorts.Contains($Port)) { $stoppedPorts.Add($Port) | Out-Null }
}

$stopFile = Join-Path $script:YXZRunDir 'supervisor.stop'
$supervisorFile = Join-Path $script:YXZRunDir 'supervisor.pid'
[int]$supervisorPid = 0

# 看门狗也得停 —— 它会检查守护进程还在不在，不在就把整套重新拉起来。
# 不先停它的话，「停止」之后过几十秒服务又全回来了。
$watchdogFile = Join-Path $script:YXZRunDir 'watchdog.pid'
$watchdogStopFile = Join-Path $script:YXZRunDir 'watchdog.stop'
[int]$watchdogPid = 0
if (Test-Path -LiteralPath $watchdogFile) {
    $raw = ([System.IO.File]::ReadAllText($watchdogFile)).Trim()
    [void][int]::TryParse($raw, [ref]$watchdogPid)
}
if ($watchdogPid -gt 0) {
    New-Item -ItemType File -Force -Path $watchdogStopFile | Out-Null
    Start-Sleep -Milliseconds 300
    if (Get-Process -Id $watchdogPid -ErrorAction SilentlyContinue) {
        Stop-YxzProcessTree -ProcId $watchdogPid | Out-Null
        if (-not $Quiet) { Ok "看门狗已停止  PID=$watchdogPid" }
    }
    Remove-Item -LiteralPath $watchdogFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $supervisorFile) {
    $raw = ([System.IO.File]::ReadAllText($supervisorFile)).Trim()
    [void][int]::TryParse($raw, [ref]$supervisorPid)
    Remove-Item -LiteralPath $supervisorFile -Force -ErrorAction SilentlyContinue
}

# 通知守护进程自己退出（它会顺手把自己的子进程带走）
New-Item -ItemType File -Force -Path $stopFile | Out-Null
if ($supervisorPid -gt 0) {
    Start-Sleep -Milliseconds 400
    if (Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue) {
        Stop-YxzProcessTree -ProcId $supervisorPid | Out-Null
        if (-not $Quiet) { Ok "守护进程已停止  PID=$supervisorPid" }
    }
}

$servicePorts = @{
    'backend' = $BackendPort
    'frontend' = $FrontendPort
    'runtime' = $RuntimePort
    'voicebox' = $VoiceboxPort
}
$serviceLabels = @{
    'backend' = '后端'
    'frontend' = '前端'
    'runtime' = 'WS通道'
    'voicebox' = '本地语音包'
}

foreach ($name in @('backend', 'frontend', 'runtime', 'voicebox')) {
    $port = [int]$servicePorts[$name]
    if ($OnlyPort -gt 0 -and $port -ne $OnlyPort) { continue }
    $hit = Stop-YxzServiceByPid -Name $name -Label $serviceLabels[$name]
    if ($hit -and -not $Quiet) { Ok "$($serviceLabels[$name]) 已停止" }
    if ($hit) { Note-Port $port }
}

function Stop-ProjectInstances {
    param([int]$From, [int]$To, [string]$Label, [scriptblock]$IsOurs)
    $listening = Get-ListeningPorts
    for ($p = $From; $p -le $To; $p++) {
        if (-not $listening.Contains($p)) { continue }
        if (-not (& $IsOurs $p)) { continue }
        $conns = Get-NetTCPConnection -LocalPort $p -State Listen
        foreach ($c in $conns) {
            if (Stop-YxzProcessTree -ProcId ([int]$c.OwningProcess)) {
                if (-not $Quiet) { Ok "$Label (: $p) 已停止  PID=$($c.OwningProcess)" }
                Note-Port $p
            }
        }
    }
}

if ($OnlyPort -eq 0 -or ($OnlyPort -ge 5199 -and $OnlyPort -le 5230)) {
    Stop-ProjectInstances -From 5199 -To 5230 -Label '前端' -IsOurs { param($p) Test-FrontendIdentity "http://127.0.0.1:$p" }
}
if ($OnlyPort -eq 0 -or ($OnlyPort -ge 8000 -and $OnlyPort -le 8030)) {
    Stop-ProjectInstances -From 8000 -To 8030 -Label '后端' -IsOurs { param($p) Test-BackendIdentity "http://127.0.0.1:$p" }
}
if ($OnlyPort -eq 0 -or ($OnlyPort -ge 6121 -and $OnlyPort -le 6130)) {
    Stop-ProjectInstances -From 6121 -To 6130 -Label 'WS通道' -IsOurs { param($p) Test-ServerRuntimeIdentity -Port $p }
}
if ($OnlyPort -eq 0 -or ($OnlyPort -ge 17493 -and $OnlyPort -le 17494)) {
    Stop-ProjectInstances -From 17493 -To 17494 -Label '本地语音包' -IsOurs { param($p) Test-YxzVoiceboxIdentity -Port $p }
}

$deadline = (Get-Date).AddSeconds(30)
$pending = @($stoppedPorts | Where-Object { Test-Port $_ })
if ($pending.Count -gt 0) {
    if (-not $Quiet) { Step "等端口释放（$($pending -join ', ')）..." }
    while ((Get-Date) -lt $deadline) {
        $pending = @($stoppedPorts | Where-Object { Test-Port $_ })
        if ($pending.Count -eq 0) { break }
        Start-Sleep -Milliseconds 400
    }
    foreach ($p in $pending) {
        if (-not $Quiet) { Warn "端口 $p 还没释放，可能被别的程序占着" }
    }
}

foreach ($name in @('backend', 'frontend', 'runtime', 'voicebox')) { Clear-YxzPid $name }
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $watchdogStopFile -Force -ErrorAction SilentlyContinue

if (-not $Quiet) {
    Write-Host ""
    Say '  完成。日志在 .run 目录，需要时可用 start-all.ps1 重新拉起。' 'DarkGray'
}

