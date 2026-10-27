# =====================================================================
#  宜小智工作台 —— 停止前后端
#  会扫描端口区间，把本项目的前后端一起停掉（不会误杀其它程序）。
#  用法： pwsh -NoProfile -ExecutionPolicy Bypass -File stop-all.ps1
# =====================================================================
param([int]$BackendPort = 8000, [int]$FrontendPort = 5199)

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

function Stop-ProjectInstances {
    param([int]$From, [int]$To, [string]$Label, [scriptblock]$IsOurs)
    $hit = $false
    for ($p = $From; $p -le $To; $p++) {
        if (-not (Test-Port $p)) { continue }
        if (-not (& $IsOurs $p)) { continue }
        $conns = Get-NetTCPConnection -LocalPort $p -State Listen
        foreach ($c in $conns) {
            $proc = Get-Process -Id $c.OwningProcess
            if ($proc) {
                Stop-Process -Id $proc.Id -Force
                Ok "$Label (: $p) 已停止  PID=$($proc.Id)  $($proc.ProcessName)"
                $hit = $true
            }
        }
    }
    if (-not $hit) { Say "  $Label 没有在运行" 'DarkGray' }
}

Stop-ProjectInstances -From 5199 -To 5230 -Label '前端' -IsOurs { param($p) Test-FrontendIdentity "http://127.0.0.1:$p" }
Stop-ProjectInstances -From 8000 -To 8030 -Label '后端' -IsOurs { param($p) Test-BackendIdentity "http://127.0.0.1:$p" }

Write-Host ""
Say '  完成。日志在 .run 目录，需要时可用 start-all.ps1 重新拉起。' 'DarkGray'