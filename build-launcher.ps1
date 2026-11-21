# =====================================================================
#  宜小智工作台 —— 编译一键启动 EXE
#
#  用 Windows 自带的 .NET Framework csc.exe 编译 launcher\YXZLauncher.cs，
#  不需要装 Visual Studio，也不需要 .NET SDK —— 换到任何一台
#  Windows 电脑都能重新编译。
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File build-launcher.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File build-launcher.ps1 -OutputDir "D:\包"
# =====================================================================
param(
    [string]$SourceRoot,
    [string]$OutputDir,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SourceRoot) { $SourceRoot = $scriptDir }
if (-not $OutputDir) { $OutputDir = $SourceRoot }

function Info($m) { if (-not $Quiet) { Write-Host "  $m" -ForegroundColor DarkCyan } }
function Ok($m) { if (-not $Quiet) { Write-Host "  [OK] $m" -ForegroundColor Green } }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

$source = Join-Path $SourceRoot 'launcher\YXZLauncher.cs'
if (-not (Test-Path -LiteralPath $source)) {
    Fail "找不到源码：$source"
    exit 1
}

# csc.exe：优先 64 位，没有就用 32 位（.NET Framework 4.x 自带）。
$candidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$csc = $null
foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) { $csc = $c; break }
}
if (-not $csc) {
    Fail "这台机器上没有 .NET Framework csc.exe，无法编译 EXE。"
    exit 1
}
Info "编译器：$csc"

# csc 按系统 ANSI 代码页读没有 BOM 的源码，中文会变成乱码甚至编译失败。
# 所以编译前先给源码补上 UTF-8 BOM。
$bytes = [System.IO.File]::ReadAllBytes($source)
if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    [System.IO.File]::WriteAllText(
        $source, $text, (New-Object System.Text.UTF8Encoding($true)))
    Info "已给源码补上 UTF-8 BOM"
}

$icon = Join-Path $SourceRoot 'airi\apps\stage-web\public\favicon.ico'
$exe = Join-Path $OutputDir '宜小智工作台.exe'

$args = @(
    '/nologo',
    '/target:winexe',
    '/platform:anycpu',
    '/optimize+',
    '/warn:3',
    "/out:`"$exe`"",
    "/reference:System.dll",
    "/reference:System.Drawing.dll",
    "/reference:System.Windows.Forms.dll",
    "/reference:System.Net.Http.dll"
)
if (Test-Path -LiteralPath $icon) {
    $args += "/win32icon:`"$icon`""
    Ok "图标：$icon"
}
$args += "`"$source`""

Write-Host "" -ForegroundColor Cyan
Write-Host "宜小智工作台 —— 编译启动 EXE" -ForegroundColor Cyan

$output = & $csc @args 2>&1
if ($LASTEXITCODE -ne 0) {
    $output | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Fail "编译失败（exit $LASTEXITCODE）"
    exit 1
}
if (-not (Test-Path -LiteralPath $exe)) {
    Fail "编译结束但没有生成 EXE"
    exit 1
}

Ok ("生成：" + $exe + "  (" + [math]::Round((Get-Item $exe).Length / 1KB, 1) + " KB)")
Write-Host ""
