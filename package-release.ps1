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

Write-Host "[2/6] 拷贝前端 airi ..." -ForegroundColor Cyan
Copy-Clean -Src (Join-Path $SourceRoot 'airi') -Dst (Join-Path $OutDir 'airi') `
    -ExcludeDirs @('node_modules', '.git', '.turbo', '.cache', 'dist', 'logs', 'tmp',
                   '__pycache__', 'coverage', '.output', '.vite', 'test-results') `
    -ExcludeFiles @('*.log', '.eslintcache', '.dev.err.log', '.parts.log', '.chain.log')
Ok "airi"

Write-Host "[3/6] 拷贝后端 cartoon-print-studio ..." -ForegroundColor Cyan
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
Write-Host "[4/6] 补回现场素材 ..." -ForegroundColor Cyan
foreach ($name in $keepData) {
    $src = Join-Path $SourceRoot ("cartoon-print-studio\data\{0}" -f $name)
    if (Test-Path -LiteralPath $src) {
        Copy-Clean -Src $src -Dst (Join-Path $OutDir ("cartoon-print-studio\data\{0}" -f $name)) `
            -ExcludeDirs @() -ExcludeFiles @('*.log')
        Info "data\$name"
    }
}

# 预制 3D 模型（4 个宜小智姿态）：模型文件太大没有进 git，只能随包走，
# 否则换电脑后"宜小智预制 3D 模型示例"整块是空的。
Write-Host "[5/6] 拷贝预制模型 presets ..." -ForegroundColor Cyan
Copy-Clean -Src (Join-Path $SourceRoot 'presets') -Dst (Join-Path $OutDir 'presets') `
    -ExcludeDirs @() -ExcludeFiles @()
Ok "presets"

Write-Host "[6/6] 拷贝根目录交付脚本 ..." -ForegroundColor Cyan
Get-ChildItem -LiteralPath $SourceRoot -File | Where-Object {
    $_.Name -ne '.gitignore'
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $OutDir $_.Name) -Force
}
Ok "根目录文件"

# keys.txt 必须随包走（不提交 GitHub，但转移电脑必需）。
$keySrc = Join-Path $SourceRoot 'cartoon-print-studio\keys.txt'
if (Test-Path -LiteralPath $keySrc) {
    Warn "keys.txt 已随包拷贝（请勿提交 GitHub）"
}
else {
    Warn "源 keys.txt 未找到，转移电脑后需要手动补齐 API key"
}

$size = (Get-ChildItem -LiteralPath $OutDir -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum / 1MB
Write-Host ("  交付目录大小: {0:N1} MB" -f $size) -ForegroundColor Green

if ($SkipZip) {
    Write-Host "已跳过打包 ZIP（-SkipZip）" -ForegroundColor Green
    exit 0
}

$zip = Join-Path (Split-Path -Parent $OutDir) 'yxz-3d-release.zip'
Write-Host "生成 ZIP ..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zip -CompressionLevel Optimal
Ok ("ZIP: {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))

Write-Host "" -ForegroundColor Green
Write-Host "完成！" -ForegroundColor Green
Write-Host "  目录: $OutDir"
Write-Host "  ZIP : $zip"
Write-Host ""
Write-Host "新电脑：进入目录先运行 install-new-pc.ps1，再运行 start-all.ps1。"
Write-Host "start-all.ps1 会自动调用 gen-provider-bootstrap.ps1，从 keys.txt 生成"
Write-Host "前端服务商配置；没有这一步前端是没有 LLM / TTS 服务商的。"
