# =====================================================================
#  宜小智工作台 —— 交付打包脚本
#
#  把仓库里的前端（airi）、后端（cartoon-print-studio）、预制模型
#  （presets）和交付脚本合并成一个干净目录，并生成 ZIP。
#
#  排除 node_modules / 虚拟环境 / 缓存等可再生内容，避免打包出一堆
#  几百兆的垃圾；保留预制 3D 模型、宜小智角色模型、名片模板和 keys.txt，
#  这些是换电脑后立刻能用的现场素材。
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File package-release.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File package-release.ps1 -SkipZip
# =====================================================================
param(
    [string]$SourceRoot,
    [string]$OutDir,
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $SourceRoot) { $SourceRoot = $scriptDir }
if (-not $OutDir) { $OutDir = Join-Path (Split-Path -Parent $SourceRoot) 'yxz-3d-release' }

function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Info($m) { Write-Host "  [$m]" -ForegroundColor DarkCyan }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }

function Copy-Clean {
    param([string]$Src, [string]$Dst, [string[]]$ExcludeDirs, [string[]]$ExcludeFiles)
    if (-not (Test-Path -LiteralPath $Src)) {
        Warn "源目录不存在，跳过：$Src"
        return
    }
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    $robocopyArgs = @($Src, $Dst, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    foreach ($d in $ExcludeDirs) { $robocopyArgs += @('/XD', $d) }
    foreach ($f in $ExcludeFiles) { $robocopyArgs += @('/XF', $f) }
    & robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败: $Src -> $Dst (exit $LASTEXITCODE)" }
}

Write-Host "" -ForegroundColor Cyan
Write-Host "宜小智工作台 —— 交付打包" -ForegroundColor Cyan
Write-Host "  源目录: $SourceRoot"
Write-Host "  输出  : $OutDir"
Write-Host "" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $SourceRoot)) { throw "源目录不存在: $SourceRoot" }

# 每次都从空目录重建：上一次打包可能拷进了现在不该带的大目录，
# 只做增量拷贝会让旧文件一直赖在交付包里。
if (Test-Path -LiteralPath $OutDir) {
    Write-Host "[1/6] 清理旧的打包目录 ..." -ForegroundColor Cyan
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "[2/7] 拷贝前端 airi ..." -ForegroundColor Cyan
Copy-Clean -Src (Join-Path $SourceRoot 'airi') -Dst (Join-Path $OutDir 'airi') `
    -ExcludeDirs @('node_modules', '.git', '.turbo', '.cache', 'dist', 'logs', 'tmp',
                   '__pycache__', 'coverage', '.output', '.vite', 'test-results',
                   '.pytest_cache', '.run', '.next', 'storybook-static') `
    -ExcludeFiles @('*.log', '.eslintcache', '.dev.err.log', '.parts.log', '.chain.log')
Ok "airi"

Write-Host "[3/7] 拷贝后端 cartoon-print-studio ..." -ForegroundColor Cyan
Copy-Clean -Src (Join-Path $SourceRoot 'cartoon-print-studio') -Dst (Join-Path $OutDir 'cartoon-print-studio') `
    -ExcludeDirs @('venv', '.venv', 'models', 'logs', 'dist', 'release', 'build',
                   '__pycache__', '.run', '.pytest_cache', 'data', '.git') `
    -ExcludeFiles @('*.log', 'software_paths.json')
Ok "cartoon-print-studio"

# 运行数据只带现场必需的素材，测试生成的会话模型不随包（体积大且没用）：
#   laser                  名片模板与已生成的名片
#   yxz_character_tripo    宜小智角色模型（GLB/OBJ/STL）
#   yxz_character_tripo_jpg 宜小智角色模型（高清版）
#   34e5c9f0a0b0           混元 3D 云端生成的一次成品交付
$keepData = @('laser', 'yxz_character_tripo', 'yxz_character_tripo_jpg', '34e5c9f0a0b0')
Write-Host "[4/7] 补回现场素材 ..." -ForegroundColor Cyan
foreach ($name in $keepData) {
    $src = Join-Path $SourceRoot ("cartoon-print-studio\data\{0}" -f $name)
    if (Test-Path -LiteralPath $src) {
        Copy-Clean -Src $src -Dst (Join-Path $OutDir ("cartoon-print-studio\data\{0}" -f $name)) `
            -ExcludeDirs @() -ExcludeFiles @('*.log', '*.blend', '*.blend1')
        Info "data\$name"
    }
}

# data 根目录下还有值得带走的东西：
#   edge_voices.json      Edge 免费音色清单快照 —— 官方接口 503 / 断网时仍能选音色
#   provider_health.json  不带：那是本机的熔断器状态，换机器应该从干净状态开始
foreach ($name in @('edge_voices.json')) {
    $src = Join-Path $SourceRoot ("cartoon-print-studio\data\{0}" -f $name)
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $OutDir ("cartoon-print-studio\data\{0}" -f $name)) -Force
        Info "data\$name"
    }
}

# 预制 3D 模型（4 个宜小智姿态）：模型文件太大没有进 git，只能随包走，
# 否则换电脑后"宜小智预制 3D 模型示例"整块是空的。
Write-Host "[5/7] 拷贝预制模型 presets ..." -ForegroundColor Cyan
Copy-Clean -Src (Join-Path $SourceRoot 'presets') -Dst (Join-Path $OutDir 'presets') `
    -ExcludeDirs @() -ExcludeFiles @()
Ok "presets"

Write-Host "[6/7] 拷贝根目录交付脚本 ..." -ForegroundColor Cyan
# .gitignore 也带走：它里面写着 keys.txt / .env.local 不入库，
# 万一有人在这个目录里 git init，密钥不会被误提交。
Get-ChildItem -LiteralPath $SourceRoot -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $OutDir $_.Name) -Force
}
# 根目录的 scripts/ 是项目自己的工具脚本（名片模板生成等），
# 跟着仓库一起走，换机器后不用再从别处捞。
$rootScripts = Join-Path $SourceRoot 'scripts'
if (Test-Path -LiteralPath $rootScripts) {
    Copy-Clean -Src $rootScripts -Dst (Join-Path $OutDir 'scripts') `
        -ExcludeDirs @('__pycache__') -ExcludeFiles @('*.log')
    Info "scripts"
}
Ok "根目录文件"

# 本地语音识别模型（faster-whisper）随包带走：换一台电脑、或者现场没有
# 网络，语音输入照样能用。模型有几百兆，所以不提交 GitHub，只随交付包走。
Write-Host "[7/7] 拷贝本地语音识别模型 ..." -ForegroundColor Cyan
$asrModel = Join-Path $SourceRoot 'cartoon-print-studio\models\asr'
if (Test-Path -LiteralPath $asrModel) {
    Copy-Clean -Src $asrModel -Dst (Join-Path $OutDir 'cartoon-print-studio\models\asr') `
        -ExcludeDirs @() `
        -ExcludeFiles @('*.metadata', '*.lock', '*.incomplete', '.gitignore', 'CACHEDIR.TAG')
    Info "models\asr"
}
else {
    Warn "未找到本地语音识别模型（首次启动时会自动下载）"
}

# keys.txt 必须随包走（不提交 GitHub，但转移电脑必需）。
$keySrc = Join-Path $SourceRoot 'cartoon-print-studio\keys.txt'
if (Test-Path -LiteralPath $keySrc) {
    Warn "keys.txt 已随包拷贝（请勿提交 GitHub）"
}
else {
    Warn "源 keys.txt 未找到，转移电脑后需要手动补齐 API key"
}

# ---- 交付前自检：缺一个都不能出包 --------------------------------
# 打包最怕的是"少拷了一个文件，别的机器上某个功能莫名其妙没了"。
# 这里把整条链路上真正吃文件的环节列出来，缺任何一项直接失败，
# 不让残包流出去。
Write-Host "[自检] 校验关键文件 ..." -ForegroundColor Cyan
$mustHave = @(
    'cartoon-print-studio\keys.txt',
    'cartoon-print-studio\backend\server.py',
    'cartoon-print-studio\backend\provider_health.py',
    'cartoon-print-studio\backend\tripo_api.py',
    'cartoon-print-studio\backend\hunyuan_cloud_api.py',
    'cartoon-print-studio\backend\edge_tts_api.py',
    'cartoon-print-studio\data\edge_voices.json',
    'airi\apps\stage-web\.env.local',
    'airi\apps\stage-web\public\provider-seed.json',
    'airi\packages\stage-ui\src\components\scenes\YXZPetScene.vue',
    'airi\packages\stage-ui\src\components\scenes\YXZLaserCardMessageCard.vue',
    'airi\packages\stage-ui\src\components\scenes\YXZCreationWorkbench.vue',
    'airi\packages\stage-ui\src\assets\yxz\layers\manifest.json',
    'airi\packages\stage-ui\src\assets\yxz\layers\body.png',
    'airi\packages\stage-ui-three\src\components\YXZRealModelScene.vue',
    'airi\packages\stage-ui\src\composables\use-yxz-print-preview.ts',
    'airi\packages\stage-ui\src\composables\use-yxz-voice-input.ts',
    'start-all.ps1',
    'stop-all.ps1',
    'install-new-pc.ps1',
    'verify-install.ps1',
    'gen-provider-bootstrap.ps1',
    'supervise-all.ps1',
    '一键部署并启动.bat',
    '停止服务.bat',
    '交付使用说明.md'
)
$missing = @()
foreach ($rel in $mustHave) {
    if (-not (Test-Path -LiteralPath (Join-Path $OutDir $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) {
    foreach ($m in $missing) { Write-Host "  [FAIL] 缺失: $m" -ForegroundColor Red }
    throw "打包自检未通过：缺 $($missing.Count) 个关键文件"
}
Ok "关键文件齐全（$($mustHave.Count) 项）"

# 预制模型：4 个宜小智姿态，少一个展厅就是空的
$presetModels = @(Get-ChildItem (Join-Path $OutDir 'presets') -Recurse -Filter 'model.glb' -File -ErrorAction SilentlyContinue)
if ($presetModels.Count -lt 4) {
    Warn "预制 3D 模型只有 $($presetModels.Count) 个（应为 4）"
}
else {
    Ok "预制 3D 模型 $($presetModels.Count) 个"
}

$size = (Get-ChildItem -LiteralPath $OutDir -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum / 1MB
Write-Host ("  交付目录大小: {0:N1} MB" -f $size) -ForegroundColor Green

# ---- 生成包内清单 -------------------------------------------------
Write-Host "[自检] 生成包内清单 ..." -ForegroundColor Cyan
$manifest = Join-Path $OutDir '包内清单.txt'
$allFiles = @(Get-ChildItem -LiteralPath $OutDir -Recurse -File -ErrorAction SilentlyContinue)
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('宜小智工作台 交付包清单')
$lines.Add("生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$lines.Add("源目录  : $SourceRoot")
$lines.Add('')
$lines.Add(('大小(KB)'.PadRight(12) + '相对路径'))
$lines.Add(('-' * 100))
foreach ($f in ($allFiles | Sort-Object FullName)) {
    $rel = $f.FullName.Substring($OutDir.Length).TrimStart('\')
    $lines.Add(([math]::Round($f.Length / 1KB, 1).ToString().PadRight(12) + $rel))
}
$lines.Add('')
$lines.Add("文件总数: $($allFiles.Count)")
[System.IO.File]::WriteAllLines($manifest, $lines, (New-Object System.Text.UTF8Encoding($true)))
Ok "包内清单.txt"

if ($SkipZip) {
    Write-Host "已跳过打包 ZIP（-SkipZip）" -ForegroundColor Green
    exit 0
}

$zip = Join-Path (Split-Path -Parent $OutDir) 'yxz-3d-release.zip'
Write-Host "生成 ZIP ..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zip -CompressionLevel Optimal
Ok ("ZIP: {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
$sha = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
[System.IO.File]::WriteAllText(
    (Join-Path (Split-Path -Parent $OutDir) 'yxz-3d-release.zip.sha256'),
    "$sha  yxz-3d-release.zip`r`n",
    (New-Object System.Text.ASCIIEncoding))
Ok "SHA256: $sha"

Write-Host "" -ForegroundColor Green
Write-Host "完成！" -ForegroundColor Green
Write-Host "  目录: $OutDir"
Write-Host "  ZIP : $zip"
Write-Host ""
Write-Host "新电脑：解压覆盖后双击「一键部署并启动.bat」即可。"
Write-Host "  依赖缺失会自动调用 install-new-pc.ps1 安装；"
Write-Host "  启动时自动从 keys.txt 重新生成前端服务商配置。"
Write-Host "  装完可用 verify-install.ps1 做整机体检。"
Write-Host ""
Write-Host "提醒：本包含真实 API key，请勿公开传播。" -ForegroundColor Yellow
