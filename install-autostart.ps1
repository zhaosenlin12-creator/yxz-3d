# =====================================================================
#  宜小智工作台 —— 开机自动启动
#
#  开机之后不用再手动双击启动.bat，展馆那台机器自己就起来了。
#
#  两条路：
#    1. Windows 计划任务（需要管理员权限）—— 最干净，登录即启动，
#       并且带一条每 5 分钟重复的看门狗任务，守护进程被杀了也会复活。
#    2. 启动文件夹（不需要任何权限）—— 往 shell:startup 里放两个
#       快捷脚本，效果一样，只是没有任务面板可以看。
#  权限不够时自动退回第 2 条路，不报错也不罢工。
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-autostart.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove
#    powershell -NoProfile -ExecutionPolicy Bypass -File install-autostart.ps1 -RunNow
# =====================================================================
param(
    [string]$TaskName = 'YXZ-Workstation-AutoStart',
    [string]$WatchdogTaskName = 'YXZ-Workstation-Watchdog',
    [switch]$Remove,
    [switch]$RunNow
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

$startScript = Join-Path $root 'start-all.ps1'
if (-not (Test-Path -LiteralPath $startScript)) {
    Fail "找不到 start-all.ps1：$startScript"
    exit 1
}
$watchdogScript = Join-Path $root 'watchdog.ps1'

# ---- 启动文件夹（不需要管理员权限的退路）---------------------------
function Get-StartupFolder {
    try {
        $dir = [Environment]::GetFolderPath('Startup')
        if ($dir -and (Test-Path -LiteralPath $dir)) { return $dir }
    }
    catch { }
    return $null
}

function Write-StartupLauncher {
    param([string]$Path, [string]$Title, [string]$ScriptPath, [string[]]$ScriptArgs)
    $argLine = ''
    foreach ($a in $ScriptArgs) { $argLine += " `"$a`"" }
    $lines = @(
        '@echo off',
        "rem $Title",
        'start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ScriptPath + '"' + $argLine,
        ''
    )
    [System.IO.File]::WriteAllText($Path, ($lines -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
}

function Remove-StartupLauncher {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}

if ($Remove) {
    try {
        $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Ok "已删除计划任务：$TaskName"
        }
        else {
            Say "  计划任务不存在，无需删除" 'DarkGray'
        }
    }
    catch {
        Warn "删除计划任务失败：$($_.Exception.Message)"
    }
    try {
        $wd = Get-ScheduledTask -TaskName $WatchdogTaskName -ErrorAction SilentlyContinue
        if ($wd) {
            Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false
            Ok "已删除计划任务：$WatchdogTaskName"
        }
    }
    catch {
        Warn "删除看门狗任务失败：$($_.Exception.Message)"
    }
    $startup = Get-StartupFolder
    if ($startup) {
        foreach ($f in @('宜小智工作台.cmd', '宜小智看门狗.cmd')) {
            if (Remove-StartupLauncher -Path (Join-Path $startup $f)) {
                Ok "已删除启动项：$f"
            }
        }
    }
    exit 0
}

# 登录时触发即可：计划任务跑在当前用户会话里，浏览器和语音都不需要
# 额外的桌面交互权限，也不像「系统启动时」那样要求管理员权限。
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -NoBrowser"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Write-Host ""
Write-Host "  登记开机自启 ..." -ForegroundColor Cyan
Write-Host ""

$registered = $false
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
        Ok "计划任务已更新：$TaskName"
    }
    else {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description '宜小智工作台开机自动启动' | Out-Null
        Ok "计划任务已创建：$TaskName"
    }
    $registered = $true
}
catch {
    Warn "登记计划任务失败：$($_.Exception.Message)"
    Say '  计划任务需要管理员权限。改用「启动」文件夹方式，不需要任何权限。' 'DarkGray'
}

if (-not $registered) {
    $startup = Get-StartupFolder
    if (-not $startup) {
        Fail "既不能登记计划任务，也找不到启动文件夹，自动启动没法配置"
        exit 1
    }
    Write-StartupLauncher -Path (Join-Path $startup '宜小智工作台.cmd') `
        -Title '宜小智工作台开机自启' -ScriptPath $startScript -ScriptArgs @('-NoBrowser')
    Ok "已放入启动文件夹：$startup\宜小智工作台.cmd"

    if (Test-Path -LiteralPath $watchdogScript) {
        Write-StartupLauncher -Path (Join-Path $startup '宜小智看门狗.cmd') `
            -Title '宜小智看门狗' -ScriptPath $watchdogScript -ScriptArgs @()
        Ok "已放入启动文件夹：$startup\宜小智看门狗.cmd"
    }
}

if ($registered -and (Test-Path -LiteralPath $watchdogScript)) {
    try {
        $wdAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`""
        # 每 5 分钟跑一次：守护进程死了就复活，活着就立刻退出。
        $wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 5)
        $wdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
        $wdExisting = Get-ScheduledTask -TaskName $WatchdogTaskName -ErrorAction SilentlyContinue
        if ($wdExisting) {
            Set-ScheduledTask -TaskName $WatchdogTaskName -Action $wdAction -Trigger $wdTrigger -Settings $wdSettings | Out-Null
        }
        else {
            Register-ScheduledTask -TaskName $WatchdogTaskName -Action $wdAction -Trigger $wdTrigger `
                -Settings $wdSettings -Description '宜小智工作台看门狗（守护进程被杀了就拉起来）' | Out-Null
        }
        Ok "看门狗任务已登记：$WatchdogTaskName（每 5 分钟检查一次）"
    }
    catch {
        Warn "看门狗任务登记失败：$($_.Exception.Message)"
        Say '  不影响主功能，守护进程自己也会重启崩溃的服务。' 'DarkGray'
    }
}

if ($RunNow) {
    Step "立刻启动一次工作台 ..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $startScript -NoBrowser
}

Write-Host ""
Ok "搞定。开机后会自动拉起前端、后端、WS 通道和本地语音包。"
if ($registered) {
    Say "  查看状态：Get-ScheduledTask -TaskName $TaskName" 'DarkGray'
}
else {
    Say "  查看状态：启动文件夹里的「宜小智工作台.cmd」" 'DarkGray'
}
Say "  取消自启：.\install-autostart.ps1 -Remove" 'DarkGray'
Write-Host ""

