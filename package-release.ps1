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
    [switch]$SkipZip,
    [switch]$SkipExe
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $SourceRoot) { $SourceRoot = $scriptDir }
if (-not $OutDir) { $OutDir = Join-Path (Split-Path -Parent $SourceRoot) 'yxz-3d-release' }

function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Info($m) { Write-Host "  [$m]" -ForegroundColor DarkCyan }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }

# SHA256 用 .NET 直接算。Get-FileHash 是个 cmdlet，要靠 PowerShell 的模块
# 自动加载；有些启动方式（Start-Process 带输出重定向）加载不到，它就会报
# "无法将 Get-FileHash 识别为 cmdlet"，脚本直接断在最后一步，.sha256
# 也没写出来。.NET 的接口在任何宿主里都可用。
function Get-Sha256 {
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($Path)
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
    } finally {
        if ($stream) { $stream.Dispose() }
        $sha.Dispose()
    }
}

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
                   '__pycache__', '.run', '.pytest_cache', 'data', '.git', 'tests') `
    -ExcludeFiles @('*.log', 'software_paths.json')
Ok "cartoon-print-studio"

# ---- 运行数据：只带"换机后立刻能跑"的素材 --------------------------
#
# 这里面每一项都做过引用核对（后端 / 前端 / 脚本全仓库 grep 过），
# 拿掉的东西要么运行时会自己生成，要么是测试会话残留：
#
#   edge_voices.json            Edge 免费音色清单快照 —— 官方接口 503 / 断网时仍能选音色
#   yxz_character_tripo/model/  宜小智角色网格（GLB + STL）
#                               frontend/yxz-character.html 直接读 mesh.glb
#   yxz_character_tripo_jpg/model/model_web.glb
#                               离线重建 2D 分层形象（airi/scripts/build_yxz_*.ps1）用的源网格，
#                               只要这一个文件；同目录下的 .blend 工程、口型变体全不带
#
# 明确不带：
#   data/laser/*                名片背面模板由 backend/assets/laser 在启动时自动镜像到
#                               data/laser/template（laser_card.ensure_templates），
#                               模板图已经在仓库里；历史会话卡片是测试残留
#   data/34e5c9f0a0b0           一次混元云端交付样品（126MB），代码零引用
#   data/provider_health.json   本机熔断器状态，换机器应该从干净状态开始
Write-Host "[4/7] 补回现场素材 ..." -ForegroundColor Cyan
$dataSrc = Join-Path $SourceRoot 'cartoon-print-studio\data'
$dataDst = Join-Path $OutDir 'cartoon-print-studio\data'
New-Item -ItemType Directory -Force -Path $dataDst | Out-Null

# 只拷指定文件（而不是整个目录），保证包里不会混进测试残留。
$dataFiles = @(
    'edge_voices.json',
    'yxz_character_tripo\model\mesh.glb',
    'yxz_character_tripo\model\mesh.stl',
    'yxz_character_tripo\previews\img_0.png',
    'yxz_character_tripo_jpg\model\model_web.glb'
)
foreach ($rel in $dataFiles) {
    $src = Join-Path $dataSrc $rel
    if (-not (Test-Path -LiteralPath $src)) {
        Warn "缺少素材，跳过：data\$rel"
        continue
    }
    $dst = Join-Path $dataDst $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Info "data\$rel"
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
# launcher/ 是 EXE 的源码，换台机器想重新编译时用得上。
$launcherDir = Join-Path $SourceRoot 'launcher'
if (Test-Path -LiteralPath $launcherDir) {
    Copy-Clean -Src $launcherDir -Dst (Join-Path $OutDir 'launcher') `
        -ExcludeDirs @('__pycache__') -ExcludeFiles @('*.log')
    Info "launcher"
}
Ok "根目录文件"

# 编译一键启动 EXE：双击就能起服务、开网页、停服务。
# 用 Windows 自带的 csc.exe，换一台机器也能重新编译。
if (-not $SkipExe) {
    Write-Host "[6b/8] 编译启动 EXE ..." -ForegroundColor Cyan
    $launcherBuild = Join-Path $SourceRoot 'build-launcher.ps1'
    if (Test-Path -LiteralPath $launcherBuild) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $launcherBuild -SourceRoot $SourceRoot -OutputDir $OutDir
        if ($LASTEXITCODE -ne 0) { throw "编译启动 EXE 失败" }
    }
    else {
        Warn "未找到 build-launcher.ps1，跳过 EXE 编译"
    }
}
else {
    Write-Host "[6b/8] 跳过 EXE 编译" -ForegroundColor Cyan
}

# 本地语音识别模型（faster-whisper）随包带走：换一台电脑、或者现场没有
# 网络，语音输入照样能用。模型有几百兆，所以不提交 GitHub，只随交付包走。
#
# 只带 small —— 它是 asr_api.py 的默认模型（YXZ_ASR_MODEL=small），
# fetch-models.ps1 也只拉这一份。仓库里那份 faster-whisper-base 全项目
# 无人引用，纯占 138MB，扔掉。
Write-Host "[7/7] 拷贝本地语音识别模型 ..." -ForegroundColor Cyan
$asrModel = Join-Path $SourceRoot 'cartoon-print-studio\models\asr\faster-whisper-small'
if (Test-Path -LiteralPath $asrModel) {
    Copy-Clean -Src $asrModel -Dst (Join-Path $OutDir 'cartoon-print-studio\models\asr\faster-whisper-small') `
        -ExcludeDirs @('.cache') `
        -ExcludeFiles @('*.metadata', '*.lock', '*.incomplete', '.gitignore', 'CACHEDIR.TAG')
    Info "models\asr\faster-whisper-small"
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
    'cartoon-print-studio\backend\llm_client.py',
    'cartoon-print-studio\backend\api_image.py',
    'cartoon-print-studio\data\edge_voices.json',
    'cartoon-print-studio\data\yxz_character_tripo\model\mesh.glb',
    'cartoon-print-studio\data\yxz_character_tripo_jpg\model\model_web.glb',
    'cartoon-print-studio\backend\assets\laser\activity_yichang.png',
    'cartoon-print-studio\models\asr\faster-whisper-small\model.bin',
    'airi\apps\stage-web\.env.local',
    'airi\apps\stage-web\public\provider-seed.json',
    'airi\packages\stage-ui\src\components\scenes\YXZPetScene.vue',
    'airi\packages\stage-ui\src\components\scenes\YXZLaserCardMessageCard.vue',
    'airi\packages\stage-ui\src\components\scenes\YXZCreationWorkbench.vue',
    'airi\packages\stage-ui\src\assets\yxz\layers\manifest.json',
    'airi\packages\stage-ui\src\assets\yxz\layers\body.png',
    'airi\packages\stage-ui-three\src\components\YXZRealModelScene.vue',
    'airi\packages\stage-ui\src\composables\use-yxz-print-preview.ts',
    'airi\packages\stage-ui\src\composables\use-yxz-requirement-memory.ts',
    'airi\packages\stage-ui\src\composables\use-yxz-voice-input.ts',
    'launcher\YXZLauncher.cs',
    'start-all.ps1',
    'stop-all.ps1',
    'build-launcher.ps1',
    'install-new-pc.ps1',
    'verify-install.ps1',
    'gen-provider-bootstrap.ps1',
    'supervise-all.ps1',
    '一键部署并启动.bat',
    '停止服务.bat',
    '交付使用说明.md'
)

# EXE 是交付包的主入口：没有它，双击就用不了。
if (-not $SkipExe) {
    $mustHave += '宜小智工作台.exe'
}
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
$sha = Get-Sha256 -Path $zip
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
Write-Host "或者：直接双击「宜小智工作台.exe」—— 窗口里点「打开宜小智」即可，"
Write-Host "  点「停止服务」会干净停掉整套进程并释放端口。"
Write-Host ""
Write-Host "提醒：本包含真实 API key，请勿公开传播。" -ForegroundColor Yellow
