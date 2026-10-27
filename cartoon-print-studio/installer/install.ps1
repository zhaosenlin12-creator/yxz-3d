# install.ps1 - deploy Cartoon Print Studio to a customer machine
# Usage:  powershell -ExecutionPolicy Bypass -File installer\install.ps1
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\CartoonPrintStudio",
    [string]$BundleDir = (Join-Path $PSScriptRoot "CartoonPrintStudio"),
    [bool]$CreateShortcut = $true
)

$ErrorActionPreference = "Stop"
$Bundle = (Resolve-Path -LiteralPath $BundleDir).Path

if (-not (Test-Path $Bundle)) {
    Write-Host "ERROR: $Bundle not found. Run installer\build.ps1 first." -ForegroundColor Red
    exit 1
}

$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$InstallDirPrefix = $Bundle.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if ($Bundle.Equals($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) -or $Bundle.StartsWith($InstallDirPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallDir must not be the distributable bundle or one of its parent directories."
}

# Pre-flight: check WebView2 Runtime (needed by the PyWebView GUI shell)
function Test-WebView2 {
    $paths = @(
        "$env:ProgramFiles (x86)\Microsoft\EdgeWebView\Application",
        "$env:ProgramFiles\Microsoft\EdgeWebView\Application"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return $true }
    }
    # Registry check (Edge stable ships WebView2)
    foreach ($reg in @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )) {
        if (Test-Path $reg) { return $true }
    }
    return $false
}

if (-not (Test-WebView2)) {
    Write-Host "WARNING: WebView2 Runtime not detected." -ForegroundColor Yellow
    Write-Host "  Cartoon Print Studio needs it for the native window." -ForegroundColor Yellow
    Write-Host "  Win11 has it built in. Win10 will auto-download on first run." -ForegroundColor Yellow
    Write-Host "  Manual install: https://developer.microsoft.com/microsoft-edge/webview2/" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "Installing to $InstallDir..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$robocopyArgs = @($Bundle, $InstallDir, "/E", "/XF", "keys.txt", "/XD", "data", "logs", "/NJH", "/NJS", "/NDL", "/NFL", "/NP")
& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Program file copy failed (robocopy exit code $LASTEXITCODE)."
}

$DemoSource = Join-Path $Bundle "data\demo"
$DemoTarget = Join-Path $InstallDir "data\demo"
if ((Test-Path -LiteralPath (Join-Path $DemoSource "model\mesh.glb")) -and -not (Test-Path -LiteralPath (Join-Path $DemoTarget "model\mesh.glb"))) {
    foreach ($Directory in @((Join-Path $DemoTarget "model"), (Join-Path $DemoTarget "previews"))) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
    foreach ($RelativeFile in @("model\mesh.glb", "model\mesh.stl", "model\mesh.obj", "previews\img_0.png", "demo.json")) {
        $SourceFile = Join-Path $DemoSource $RelativeFile
        if ((Test-Path -LiteralPath $SourceFile) -and -not (Test-Path -LiteralPath (Join-Path $DemoTarget $RelativeFile))) {
            Copy-Item -LiteralPath $SourceFile -Destination (Join-Path $DemoTarget $RelativeFile)
        }
    }
}

# Launcher .cmd
$launcher = Join-Path $InstallDir "CartoonPrintStudio.cmd"
$launcherContent = "@echo off`r`ncd /d `"%~dp0`"`r`nstart `"`" `"CartoonPrintStudio.exe`"`r`n"
Set-Content -Path $launcher -Value $launcherContent -Encoding ascii

# Keys and user data are never overwritten during upgrades.
$keysLocal = Join-Path $InstallDir "keys.txt"
$keysDesktop = [Environment]::GetFolderPath("Desktop") | Join-Path -ChildPath "key.txt"
if ((Test-Path $keysDesktop) -and -not (Test-Path $keysLocal)) {
    Copy-Item $keysDesktop $keysLocal
    Write-Host "Seeded $keysLocal from Desktop\key.txt"
} elseif (-not (Test-Path $keysLocal)) {
    @"
# Per-device API keys. Add only the providers this PC is authorized to use.
# minimax-key: ...
# jojo-image: ...
# TRIPO:3D模型生成
# tsk_...
"@ | Set-Content -LiteralPath $keysLocal -Encoding utf8
    Write-Host "Created a blank per-device keys.txt at $keysLocal" -ForegroundColor Yellow
}

if ($CreateShortcut) {
    $WshShell = New-Object -ComObject WScript.Shell
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $ShortcutFile = Join-Path $Desktop "Cartoon Print Studio.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutFile)
    $Shortcut.TargetPath = $launcher
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.IconLocation = Join-Path $InstallDir "CartoonPrintStudio.exe"
    $Shortcut.Description = "Cartoon Print Studio - AI 3D Figurine Generator"
    $Shortcut.Save()
    Write-Host "Created desktop shortcut: $ShortcutFile"
}

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Cartoon Print Studio installed!" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Location: $InstallDir"
Write-Host "  Launch:   Double-click 'Cartoon Print Studio' on your Desktop"
Write-Host ""
Write-Host "  First run: native window opens (no browser needed)."
Write-Host "  Make sure Bambu Studio is installed for one-click printing."
Write-Host "===========================================" -ForegroundColor Cyan
