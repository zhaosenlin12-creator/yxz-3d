# =====================================================================
#  宜小智工作台 —— 看门狗
#
#  守护进程（supervise-all.ps1）负责在服务崩溃时把服务拉起来。但如果
#  守护进程自己被杀掉（机器休眠后唤醒失败、被安全软件清理、或者系统
#  更新重启了后台任务），四个服务就再也没人管了。
#
#  这个脚本是守护进程的最后一道保险：每隔一段时间看一眼守护进程还在
#  不在，不在就重新把它拉起来。
#
#  它只由 install-autostart.ps1 登记自启，不会被 start-all.ps1 顺手拉
#  起 —— 否则 stop-all.ps1 停完之后，看门狗又把整套东西起回来。
# =====================================================================
param(
    [int]$IntervalSec = 30,
    [switch]$Once
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null

$supervisorPidFile = Join-Path $run 'supervisor.pid'
$watchdogPidFile = Join-Path $run 'watchdog.pid'
$stopFile = Join-Path $run 'watchdog.stop'
$logFile = Join-Path $run 'watchdog.log'

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Test-SupervisorAlive {
    if (-not (Test-Path -LiteralPath $supervisorPidFile)) { return $false }
    $raw = ([System.IO.File]::ReadAllText($supervisorPidFile)).Trim()
    $id = 0
    if (-not [int]::TryParse($raw, [ref]$id)) { return $false }
    if ($id -le 0) { return $false }
    return [bool](Get-Process -Id $id -ErrorAction SilentlyContinue)
}

function Start-SupervisorIfDead {
    if (Test-SupervisorAlive) { return $false }
    Write-WatchdogLog "守护进程不在了，重新拉起"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'start-all.ps1') -NoBrowser | Out-Null
    return $true
}

Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
[System.IO.File]::WriteAllText($watchdogPidFile, [string]$PID)
Write-WatchdogLog "看门狗启动 PID=$PID 间隔=${IntervalSec}s"

try {
    if ($Once) {
        Start-SupervisorIfDead | Out-Null
        exit 0
    }
    while ($true) {
        if (Test-Path -LiteralPath $stopFile) {
            Write-WatchdogLog "收到停止指令，看门狗退出"
            break
        }
        try {
            Start-SupervisorIfDead | Out-Null
        }
        catch {
            Write-WatchdogLog "拉起守护进程时出错：$($_.Exception.Message)"
        }
        Start-Sleep -Seconds $IntervalSec
    }
}
finally {
    Remove-Item -LiteralPath $watchdogPidFile -Force -ErrorAction SilentlyContinue
    Write-WatchdogLog "看门狗已退出"
}
