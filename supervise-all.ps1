# =====================================================================
#  宜小智工作台 —— 守护进程
#
#  之前后端一崩，前端就再也起不来，只能手动重启整套东西。
#  现在这个脚本常驻后台：
#    * 四个服务（后端 / 前端 / WS通道 / 本地语音包）谁退出就拉起谁
#    * 谁活着但端口不通（卡死），超过阈值也重新拉起
#    * 连续崩溃时自动降频，避免无限重启把机器拖垮
#    * 收到 .run\supervisor.stop 或被 stop-all.ps1 收掉时优雅退出
#
#  一般不需要手动跑，start-all.ps1 会自动把它拉起来。
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [int]$RuntimePort = 6121,
    [int]$VoiceboxPort = 17493,
    [int]$IntervalSec = 5,
    [switch]$NoVoicebox,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipRuntime
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')
. (Join-Path $root 'lib-services.ps1')

Initialize-YxzRunDir
$stopFile = Join-Path $script:YXZRunDir 'supervisor.stop'
$logFile = Join-Path $script:YXZRunDir 'supervisor.log'

function Write-SupervisorLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

# 守护进程是脱离式启动的，没有控制台可写，脚本自己打印的东西（警告、
# 报错）会直接丢掉。把整个会话录进 transcript，出问题随时能查。
$transcriptFile = Join-Path $script:YXZRunDir 'supervisor.transcript.log'
try { Start-Transcript -Path $transcriptFile -Append -ErrorAction Stop } catch { }

# ---- 服务清单 --------------------------------------------------------
function New-YxzService {
    param(
        [string]$Name,
        [string]$Label,
        [int]$Port,
        [scriptblock]$ReadyTest,
        [scriptblock]$Starter
    )
    return [pscustomobject]@{
        Name = $Name
        Label = $Label
        Port = $Port
        Ready = $false
        Proc = $null
        LogErr = ''
        StartedAt = [datetime]::MinValue
        LastCheck = [datetime]::MinValue
        Fails = 0
        Restarts = @()
        ReadyTest = $ReadyTest
        Starter = $Starter
    }
}

$services = @()
if (-not $SkipBackend) {
    $services += New-YxzService -Name 'backend' -Label '后端' -Port $BackendPort `
        -ReadyTest { param($p) Test-YxzBackendReady -Port $p } `
        -Starter { param($p) Start-YxzBackend -Port $p }
}
if (-not $SkipFrontend) {
    $services += New-YxzService -Name 'frontend' -Label '前端' -Port $FrontendPort `
        -ReadyTest { param($p) Test-YxzFrontendReady -Port $p } `
        -Starter { param($p) Start-YxzFrontend -Port $p -BackendPort $BackendPort }
}
if (-not $SkipRuntime) {
    $services += New-YxzService -Name 'runtime' -Label 'WS通道' -Port $RuntimePort `
        -ReadyTest { param($p) Test-YxzRuntimeReady -Port $p } `
        -Starter { param($p) Start-YxzRuntime -Port $p }
}
if (-not $NoVoicebox) {
    # 本地语音包 Voicebox 是个可选组件：没装这台机器就没有。
    # 之前不管在不在都会去拉，每 8 秒失败一次，日志刷满、还让人以为
    # 系统坏了。这里先探一次，找不到就整段跳过，只留一句提示。
    if (Get-YxzVoiceboxRoot) {
        $services += New-YxzService -Name 'voicebox' -Label '本地语音包' -Port $VoiceboxPort `
            -ReadyTest { param($p) Test-YxzVoiceboxReady -Port $p } `
            -Starter { param($p) Start-YxzVoicebox -Port $p -FrontendPort $FrontendPort }
    }
    else {
        Write-SupervisorLog "本地语音包 Voicebox 没装（这台机器没有这个组件），跳过；TTS 走 MiniMax → Edge"
    }
}

# ---- 启动单个服务 ----------------------------------------------------
function Start-SupervisedService {
    param($Service)

    # 端口被占：把占着它的进程收干净再起。
    # 这里只能按端口直接收，绝不能去调 stop-all.ps1 —— 那个脚本会把
    # 守护进程自己也停掉，restart 就变成了自杀。
    if (Test-Port $Service.Port) {
        Write-SupervisorLog "$($Service.Label) 端口 $($Service.Port) 仍被占用，先清理"
        Clear-YxzPort -Port $Service.Port -TimeoutSec 15 | Out-Null
    }

    $proc = & $Service.Starter $Service.Port
    if (-not $proc) {
        Write-SupervisorLog "$($Service.Label) 启动失败"
        return
    }
    $Service.Proc = $proc
    $Service.Ready = $false
    $Service.Fails = 0
    $Service.StartedAt = Get-Date
    $Service.LastCheck = Get-Date
    $Service.Restarts += (Get-Date)
    $latest = Get-YxzLatestLog -Name $Service.Name -Port $Service.Port
    if ($latest) { $Service.LogErr = $latest.Err }
    Write-SupervisorLog "$($Service.Label) 已拉起 PID=$($proc.Id) 端口=$($Service.Port)"
}

# 把出错那一轮的 stderr 尾巴抄进 supervisor.log —— 后端崩溃时不用再去
# .run 目录里翻文件才知道发生了什么。
function Write-SupervisorCrashDetail {
    param($Service, [int]$ExitCode)
    $path = $Service.LogErr
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return }
    Write-SupervisorLog "$($Service.Label) 退出前日志（$([System.IO.Path]::GetFileName($path))):"
    try {
        Get-Content -LiteralPath $path -Tail 25 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-SupervisorLog "    $_" }
    }
    catch { }
}

# ---- 守护主循环 ------------------------------------------------------
Write-SupervisorLog "守护进程启动 PID=$PID"
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
[System.IO.File]::WriteAllText((Join-Path $script:YXZRunDir 'supervisor.pid'), [string]$PID)

foreach ($svc in $services) {
    # 已经健康的实例直接接管，不再重复拉起。
    #
    # 端口刚被别人交出去时，服务往往还在热身（前端要冷编译、语音包要
    # 加载模型），一次 3 秒超时就判成"不健康"，然后把好好的服务重启
    # 一遍 —— 正好赶上这一下的访客就白屏一下。所以多给几次机会再判定。
    $adopted = $false
    if (Test-Port $svc.Port) {
        for ($i = 0; $i -lt 5; $i++) {
            try { if (& $svc.ReadyTest $svc.Port) { $adopted = $true; break } } catch { }
            Start-Sleep -Seconds 2
        }
    }
    if ($adopted) {
        $svc.Ready = $true
        $svc.StartedAt = Get-Date
        Write-SupervisorLog "$($svc.Label) 已在运行（端口 $($svc.Port)），接管"
        continue
    }
    Start-SupervisedService -Service $svc
}

while ($true) {
    try {
        if (Test-Path -LiteralPath $stopFile) {
            Write-SupervisorLog "收到停止指令，守护进程退出"
            Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
            break
        }

        $now = Get-Date
        foreach ($svc in $services) {
            try {
            # 进程没了 —— 崩溃或被手动关掉，拉起来。
            if ($svc.Proc -and $svc.Proc.HasExited) {
                Write-SupervisorLog "$($svc.Label) 进程退出（代码 $($svc.Proc.ExitCode)），准备重启"
                Write-SupervisorCrashDetail -Service $svc -ExitCode $svc.Proc.ExitCode
                $svc.Proc = $null
                $svc.Ready = $false
            }

            if (-not $svc.Proc) {
                # 接管来的服务没有进程句柄，但它可能活得很好。端口还通
                # 就不要动它 —— 之前这里无条件重启，把刚接管的服务又杀
                # 一遍，访客正好赶上就是白屏一下。
                $stillAlive = $false
                try { $stillAlive = [bool](& $svc.ReadyTest $svc.Port) } catch { $stillAlive = $false }
                if ($stillAlive) {
                    if (-not $svc.Ready) {
                        Write-SupervisorLog "$($svc.Label) 仍在运行（端口 $($svc.Port)）"
                        $svc.Ready = $true
                    }
                    continue
                }
                # 崩溃太频繁时降频，别把机器拖死。
                $recent = @($svc.Restarts | Where-Object { ($now - $_).TotalMinutes -lt 5 })
                $svc.Restarts = $recent
                $cooldown = 30
                if ($recent.Count -ge 5) { $cooldown = 90 }
                $last = if ($recent.Count) { $recent[-1] } else { [datetime]::MinValue }
                if (($now - $last).TotalSeconds -ge $cooldown) {
                    Start-SupervisedService -Service $svc
                }
                continue
            }

            # 活着但不通 —— 端口一直没起来，多半是卡死了。
            if (($now - $svc.LastCheck).TotalSeconds -ge 5) {
                $svc.LastCheck = $now
                $healthy = $false
                try { $healthy = & $svc.ReadyTest $svc.Port } catch { $healthy = $false }
                if ($healthy) {
                    if (-not $svc.Ready) {
                        Write-SupervisorLog "$($svc.Label) 就绪（端口 $($svc.Port)）"
                        $svc.Ready = $true
                    }
                    $svc.Fails = 0
                }
                else {
                    $svc.Fails += 1
                    $hung = $svc.Ready -and ($svc.Fails -ge 6)
                    $neverStarted = (-not $svc.Ready) -and (($now - $svc.StartedAt).TotalSeconds -gt 150)
                    if ($hung -or $neverStarted) {
                        Write-SupervisorLog "$($svc.Label) 端口 $($svc.Port) 没响应，重启它"
                        Stop-YxzProcessTree -ProcId $svc.Proc.Id | Out-Null
                        $svc.Proc = $null
                        $svc.Ready = $false
                        $svc.Fails = 0
                        Start-SupervisedService -Service $svc
                    }
                }
            }
            }
            catch {
                # 一个服务出问题不能带倒整个守护进程。
                Write-SupervisorLog "$($svc.Label) 检查时出错：$($_.Exception.Message)"
                try { $svc.Proc = $null; $svc.Ready = $false } catch { }
            }
        }
    }
    catch {
        # 守护循环自己出错也不能退出 —— 一旦退出，四个服务就没人管了。
        Write-SupervisorLog "守护循环异常（已忽略并继续）：$($_.Exception.Message)"
        try { Write-SupervisorLog ($_.ScriptStackTrace) } catch { }
        Start-Sleep -Seconds 2
    }

    Start-Sleep -Seconds $IntervalSec
}

# ---- 收尾：把子进程一起带走 ------------------------------------------
foreach ($svc in $services) {
    if ($svc.Proc) {
        Stop-YxzProcessTree -ProcId $svc.Proc.Id | Out-Null
    }
}
try { Stop-Transcript -ErrorAction SilentlyContinue } catch { }
Write-SupervisorLog "守护进程已退出"

