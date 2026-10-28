# =====================================================================
#  宜小智工作台 —— 从 keys.txt 生成前端服务商配置 (.env.local)
#
#  为什么需要这个脚本：
#    前端的 LLM / TTS 凭据通过环境变量 VITE_LOCAL_PROVIDER_BOOTSTRAP_B64
#    注入，浏览器启动时再写进 localStorage。这个文件是 .gitignore 的
#    （不能把 key 提交进仓库），而且以前**没有任何脚本会生成它**，
#    结果就是：新机器装完前端完全没有配任何服务商 —— 对话、TTS 讲解
#    全部不可用，只能手动点进设置页一个一个填。
#
#  这个脚本把 cartoon-print-studio\keys.txt 里的 key 转成 .env.local，
#  安装脚本和启动脚本都会自动调用它。
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File gen-provider-bootstrap.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File gen-provider-bootstrap.ps1 -Force
# =====================================================================
param(
    [string]$KeysPath,
    [string]$OutputPath,
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $KeysPath) { $KeysPath = Join-Path $root 'cartoon-print-studio\keys.txt' }
if (-not $OutputPath) { $OutputPath = Join-Path $root 'airi\apps\stage-web\.env.local' }

function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }

Write-Host ""
Write-Host "生成前端服务商配置 (.env.local)" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $KeysPath)) {
    Warn "找不到 keys.txt（$KeysPath）—— 跳过生成，前端将没有 LLM / TTS 服务商"
    exit 0
}

# ---- 解析 keys.txt ---------------------------------------------------
$keyMap = @{}
foreach ($line in (Get-Content -LiteralPath $KeysPath -Encoding UTF8)) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $idx = $trimmed.IndexOf(':')
    if ($idx -lt 1) { continue }
    $name = $trimmed.Substring(0, $idx).Trim()
    $value = $trimmed.Substring($idx + 1).Trim()
    if (-not $name -or -not $value) { continue }
    $keyMap[$name] = $value
}

$minimaxKeys = @()
if ($keyMap.ContainsKey('minimax-key')) { $minimaxKeys += $keyMap['minimax-key'] }
if ($keyMap.ContainsKey('minimax-key-2')) { $minimaxKeys += $keyMap['minimax-key-2'] }

if ($minimaxKeys.Count -eq 0) {
    Warn "keys.txt 里没有 minimax-key —— 跳过生成（对话 / TTS 会不可用）"
    exit 0
}

$minimaxBase = 'https://api.minimaxi.com/v1/'

$providers = @{}
if ($keyMap.ContainsKey('deepseek-key')) {
    $providers['deepseek'] = @{
        apiKey  = $keyMap['deepseek-key']
        baseUrl = 'https://api.deepseek.com/'
    }
}

# TTS 与聊天都走 MiniMax；apiKeys 让前端在一个 key 额度用尽时自动换下一个。
foreach ($providerId in @('minimax-audio-speech', 'minimax', 'openai-compatible')) {
    $providers[$providerId] = @{
        apiKey  = $minimaxKeys[0]
        apiKeys = $minimaxKeys
        baseUrl = $minimaxBase
    }
}

# 本地语音包（Voicebox / Qwen CustomVoice）。音色不是写死的：前端启动后
# 从 http://127.0.0.1:17493/profiles 拉取声音档案，用户在设置页选中的那一个
# 会记在 settings/speech/voice 里。这里只登记服务商本身。
$providers['voicebox-local'] = @{
    baseUrl   = 'http://127.0.0.1:17493'
    model     = 'qwen-custom-voice-1.7B'
    modelSize = '1.7B'
    instruct  = '温暖、活泼、亲切，带一点可爱的卡通感，语速自然，像宜小智在和用户面对面交流。'
}

# 免费的 Edge 神经语音作为最后一道兜底：没有 key、不依赖本地语音包，
# 由本地后端渲染（edge-tts），永远保证宜小智能开口。
$providers['edge-tts-free'] = @{
    baseUrl = 'http://127.0.0.1:8000'
    model   = 'edge-tts'
    voice   = 'zh-CN-XiaoxiaoNeural'
    rate    = '+0%'
    pitch   = '+0Hz'
    volume  = '+0%'
}

$modules = @{
    consciousness = @{
        # 对话主通道：MiniMax（中国区）。provider-seed.json 也指向它，
        # 两边必须一致 —— 不一致时前端算出来的备用通道是错的。
        activeProvider = 'minimax'
        activeModel    = 'MiniMax-M2.7'
    }
    speech = @{
        # 语音链路：MiniMax 主（音色最全）→ 本地 Voicebox 语音包备 →
        # 免费 Edge 神经语音兜底。三级都能出声音，永远不会哑掉。
        activeProvider = 'minimax-audio-speech'
        activeModel    = 'speech-2.5-hd'
        voice          = 'female-shaonv'
        language       = 'zh-CN'
        fallbacks      = @(
            @{
                providerId = 'voicebox-local'
                model      = 'qwen-custom-voice-1.7B'
            },
            @{
                providerId = 'edge-tts-free'
                model      = 'edge-tts'
                voice      = 'zh-CN-XiaoxiaoNeural'
            }
        )
    }
}
if ($providers.ContainsKey('deepseek')) {
    $modules['consciousness'] = @{
        activeProvider = 'minimax'
        activeModel    = 'MiniMax-M2.7'
    }
}

$addedProviders = @($providers.Keys)

# ---- 备用对话通道 ---------------------------------------------------
#   主通道（MiniMax）抖动时，前端自己换到下一条通道继续，用户不用去
#   设置里挑模型。这里必须写清楚"服务商 + 它自己的模型名"：把主通道
#   的模型名发给备用通道，对方只会回一句"请换个模型"。
#
#   注意：早先这里用的是 openai-compatible + qwen3-max，可 openai-compatible
#   指向的其实是 MiniMax 地址，qwen3-max 在那儿根本不存在 —— 备用通道等于
#   没有，切换必然失败。
$fallbacks = @{}
if ($providers.ContainsKey('deepseek')) {
    $fallbacks['consciousness'] = @{
        cooldownMs = 300000
        candidates = @(
            @{
                providerId = 'deepseek'
                model      = 'deepseek-chat'
            }
        )
    }
}

# ---- revision 用内容哈希，key 一变就自动失效浏览器里的旧配置 --------
$core = [ordered]@{
    providers      = $providers
    addedProviders = $addedProviders
    modules        = $modules
    fallbacks      = $fallbacks
}
$coreJson = $core | ConvertTo-Json -Depth 8 -Compress
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $hashBytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($coreJson))
}
finally {
    $sha.Dispose()
}
$hash = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })

$bootstrap = [ordered]@{
    revision       = "yxz-bootstrap-$($hash.Substring(0, 12))"
    providers      = $providers
    addedProviders = $addedProviders
    modules        = $modules
    fallbacks      = $fallbacks
}

$json = $bootstrap | ConvertTo-Json -Depth 8 -Compress
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))

# ---- 写文件 ---------------------------------------------------------
$existing = $null
if (Test-Path -LiteralPath $OutputPath) {
    $existing = (Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8)
}
if ($existing -and $existing.Contains($b64) -and -not $Force) {
    Ok ".env.local 已经是最新（revision $($bootstrap.revision)），无需改动"
    exit 0
}

$content = "# 由 gen-provider-bootstrap.ps1 自动生成，请勿手工编辑。`r`n# 改 key 请改 cartoon-print-studio\keys.txt，然后重跑本脚本。`r`nVITE_LOCAL_PROVIDER_BOOTSTRAP_B64=$b64`r`n"
[System.IO.File]::WriteAllText($OutputPath, $content, (New-Object System.Text.UTF8Encoding($false)))
Ok "已生成 $OutputPath（revision $($bootstrap.revision)，服务商：$($addedProviders -join ', ')）"
exit 0
