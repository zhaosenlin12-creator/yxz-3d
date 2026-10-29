# =====================================================================
#  宜小智工作台 —— 整机体检
#
#  用途：新机器装好（或换机、升级）之后，一条命令证明"这台设备和
#  展台那台是同一套体验"，而不是靠人肉点一遍界面。
#
#  检查项分三档：
#    [OK]   正常
#    [WARN] 不影响主流程，但要知道（例：本地建模引擎没装，走云端）
#    [FAIL] 会真的影响体验，必须处理
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File verify-install.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File verify-install.ps1 -Quiet
# =====================================================================
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5199,
    [int]$RuntimePort = 6121,
    [int]$VoiceboxPort = 17493,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$fail = 0
$warn = 0

function Ok($m) {
    if (-not $Quiet) { Write-Host "  [OK]   $m" -ForegroundColor Green }
}
function Warn2($m) {
    $script:warn++
    if (-not $Quiet) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
}
function Bad($m) {
    $script:fail++
    if (-not $Quiet) { Write-Host "  [FAIL] $m" -ForegroundColor Red }
}
function Head($m) {
    if (-not $Quiet) { Write-Host "" ; Write-Host "== $m" -ForegroundColor Cyan }
}

function Get-Json($url, $timeoutSec = 10) {
    try {
        return Invoke-RestMethod -Uri $url -TimeoutSec $timeoutSec
    }
    catch {
        return $null
    }
}

function Test-Port($port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect('127.0.0.1', $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(1500, $false) -and $c.Connected
        $c.Close()
        return $ok
    }
    catch {
        return $false
    }
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  宜小智工作台 · 整机体检" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---- 1) 服务进程 ----------------------------------------------------
Head "服务进程"

$ping = Get-Json "http://127.0.0.1:$BackendPort/api/ping" 8
if ($ping -and $ping.ok) { Ok "后端 127.0.0.1:$BackendPort 正常" }
else { Bad "后端 127.0.0.1:$BackendPort 没有响应（先跑 start-all.ps1）" }

if (Test-Port $FrontendPort) { Ok "前端 127.0.0.1:$FrontendPort 已启动" }
else { Bad "前端 127.0.0.1:$FrontendPort 没有响应" }

if (Test-Port $RuntimePort) { Ok "对话通道 127.0.0.1:$RuntimePort 已启动" }
else { Warn2 "对话通道 127.0.0.1:$RuntimePort 没有响应（对话会退到浏览器直连）" }

if (Test-Port $VoiceboxPort) { Ok "本地语音包 127.0.0.1:$VoiceboxPort 已启动（TTS 第二级兜底）" }
else { Warn2 "本地语音包 127.0.0.1:$VoiceboxPort 没有响应（TTS 只剩 MiniMax 和 Edge）" }

# ---- 2) 密钥 --------------------------------------------------------
Head "密钥与服务商"

$keyFile = Join-Path $root 'cartoon-print-studio\keys.txt'
$keyMap = @{}
if (Test-Path -LiteralPath $keyFile) {
    foreach ($line in (Get-Content -LiteralPath $keyFile -Encoding UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf(':')
        if ($i -lt 1) { continue }
        $name = $t.Substring(0, $i).Trim()
        $val = $t.Substring($i + 1).Trim()
        if ($name -and $val) { $keyMap[$name] = $val }
    }
}
else {
    Bad "缺少 cartoon-print-studio\keys.txt（照 keys.txt.example 复制一份并填入）"
}

function Test-Key($label, $names, $must) {
    $found = $false
    foreach ($n in $names) { if ($keyMap.ContainsKey($n)) { $found = $true; break } }
    if ($found) { Ok "$label 已配置" }
    elseif ($must) { Bad "$label 没有配置（$($names -join ' / ')）" }
    else { Warn2 "$label 没有配置（$($names -join ' / ')）" }
}

Test-Key '对话 LLM（MiniMax 首选）' @('minimax-key', 'minimax-key-2') $true
Test-Key '备用 LLM（DeepSeek）' @('deepseek-key') $false
Test-Key '生图（MiniMax / AIXJ）' @('minimax-image-key', 'aixj-image-key', 'aixj-image-key-2') $true
Test-Key '云端 3D（Tripo）' @('TRIPO') $true
Test-Key '云端 3D（混元 备用）' @('hunyuan3d-secret-id', 'hunyuan3d-secret-key') $false

# 前端凭据（浏览器侧的对话 / TTS）
$seed = Join-Path $root 'airi\apps\stage-web\public\provider-seed.json'
if (Test-Path -LiteralPath $seed) { Ok "前端服务商种子 provider-seed.json 已生成" }
else { Bad "缺少 provider-seed.json（跑 scripts\seed_provider_seed.py 生成）" }

$envLocal = Join-Path $root 'airi\apps\stage-web\.env.local'
if (Test-Path -LiteralPath $envLocal) { Ok "前端环境配置 .env.local 已生成" }
else { Bad "缺少 .env.local（跑 gen-provider-bootstrap.ps1 生成）" }

# ---- 3) 云端能力 ----------------------------------------------------
Head "云端能力"

$health = Get-Json "http://127.0.0.1:$BackendPort/api/health" 20
if ($health) {
    if ($health.tripo3d_ok) { Ok "Tripo3D 可用（余额 $($health.tripo3d_balance)）" }
    elseif ($health.tripo3d_checking) { Warn2 "Tripo3D 正在探测中，稍后再看" }
    else { Warn2 "Tripo3D 现在探测不到（3D 会自动换混元）" }

    if ($health.minimax_alive_keys -gt 0) { Ok "MiniMax 生图可用（$($health.minimax_alive_keys) 把 key 在用）" }
    else { Warn2 "MiniMax 生图没有可用 key（会换 AIXJ / jojo）" }

    if ($health.aixj_image_keys -gt 0) { Ok "AIXJ 生图已配置（$($health.aixj_image_keys) 把）" }
    else { Warn2 "AIXJ 生图没有配置" }

    # 熔断器状态：有 provider 处于 open，说明它刚刚失败过
    if ($health.providers) {
        $open = @()
        foreach ($name in $health.providers.PSObject.Properties.Name) {
            $p = $health.providers.$name
            if ($p.state -eq 'open') { $open += "$name($([int]$p.cooldown_remaining_s)s)" }
        }
        if ($open.Count -eq 0) { Ok "所有服务商都在线" }
        else { Warn2 "暂时不可用的服务商：$($open -join ', ')" }
    }
}
else {
    Warn2 "拿不到 /api/health，无法判断云端状态"
}

# ---- 4) 语音 --------------------------------------------------------
Head "语音"

$voices = Get-Json "http://127.0.0.1:$BackendPort/api/tts/edge/voices" 20
if ($voices -and $voices.voices -and $voices.voices.Count -gt 0) {
    Ok "Edge 免费语音包可选音色 $($voices.voices.Count) 个（第三级兜底）"
}
else {
    Warn2 "Edge 音色清单暂时取不到（TTS 主通道 MiniMax 不受影响）"
}

# ---- 5) 本机软件 ----------------------------------------------------
Head "本机打印 / 激光切割软件"

$tools = Get-Json "http://127.0.0.1:$BackendPort/api/software/detect" 30
if ($tools -and $tools.tools) {
    $ready = @()
    foreach ($t in $tools.tools) {
        if ($t.available) { $ready += $t.name }
    }
    if ($ready.Count -gt 0) { Ok "检测到可用软件：$($ready -join '、')" }
    else { Warn2 "没有检测到 3D 打印 / 激光切割软件（模型和卡片仍可下载）" }
}
else {
    Warn2 "软件检测接口没有响应"
}

# ---- 6) 静态资源 ----------------------------------------------------
Head "资源与模型"

$seedFile = Join-Path $root 'airi\apps\stage-web\public\provider-seed.json'
if (Test-Path -LiteralPath $seedFile) { Ok "前端资源目录就绪" }

$weights = Join-Path $root 'cartoon-print-studio\ai\forge-webui\models'
if (Test-Path -LiteralPath $weights) {
    $gb = 0
    try {
        $bytes = (Get-ChildItem -LiteralPath $weights -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($bytes) { $gb = [math]::Round($bytes / 1GB, 1) }
    }
    catch { }
    Ok "本地 AI 权重已安装（约 $gb GB，本地生图 / 本地建模可用）"
}
else {
    Warn2 "本地 AI 权重没装（跑 fetch-models.ps1 补装；云端 3D 与云端出图不受影响）"
}

# ---- 总结 -----------------------------------------------------------
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
if ($fail -eq 0 -and $warn -eq 0) {
    Write-Host "  体检结果：全绿，可以使用" -ForegroundColor Green
}
elseif ($fail -eq 0) {
    Write-Host "  体检结果：主流程可用，$warn 项提醒" -ForegroundColor Yellow
}
else {
    Write-Host "  体检结果：$fail 项必须处理，$warn 项提醒" -ForegroundColor Red
}
Write-Host "==============================================" -ForegroundColor Cyan

exit ($(if ($fail -gt 0) { 1 } else { 0 }))
