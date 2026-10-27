# Build an isolated, secret-free field package without touching local dist/data.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PyExe = Join-Path $Root "ai\forge-webui\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PyExe)) {
    throw "Build Python was not found: $PyExe"
}

$ReleaseId = Get-Date -Format "yyyyMMdd-HHmmss"
$ReleaseRoot = Join-Path $Root "release\$ReleaseId"
$BuildWork = Join-Path $ReleaseRoot "pyinstaller-work"
$Bundle = Join-Path $ReleaseRoot "CartoonPrintStudio"
$Archive = Join-Path $ReleaseRoot "CartoonPrintStudio-Portable.zip"
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null

Write-Host "[1/4] Creating the generic offline demo..."
& $PyExe (Join-Path $PSScriptRoot "create_demo.py")
if ($LASTEXITCODE -ne 0) { throw "Demo generation failed with exit code $LASTEXITCODE" }

Write-Host "[2/4] Building the isolated application bundle..."
& $PyExe -m PyInstaller --noconfirm --clean --workpath $BuildWork --distpath $ReleaseRoot "installer\run.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath (Join-Path $Bundle "CartoonPrintStudio.exe"))) {
    throw "PyInstaller did not produce the expected executable."
}

$BundledDemo = Join-Path $Bundle "_internal\data\demo"
if (-not (Test-Path -LiteralPath (Join-Path $BundledDemo "model\mesh.glb"))) {
    throw "PyInstaller did not collect the offline demo model."
}
$InstallDemo = Join-Path $Bundle "data\demo"
New-Item -ItemType Directory -Path (Split-Path -Parent $InstallDemo) -Force | Out-Null
Copy-Item -LiteralPath $BundledDemo -Destination $InstallDemo -Recurse
Remove-Item -LiteralPath (Join-Path $Bundle "_internal\data") -Recurse -Force

if (Test-Path -LiteralPath (Join-Path $Bundle "keys.txt")) {
    throw "A local keys.txt was included in the distributable bundle."
}
if (-not (Test-Path -LiteralPath (Join-Path $Bundle "data\demo\model\mesh.glb"))) {
    throw "The offline demo model is missing from the bundle."
}

Write-Host "[3/4] Creating the portable ZIP..."
$PortableRoot = Join-Path $ReleaseRoot "portable"
$PortableApp = Join-Path $PortableRoot "CartoonPrintStudio"
Copy-Item -LiteralPath $Bundle -Destination $PortableApp -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination (Join-Path $PortableRoot "install.ps1")
Compress-Archive -LiteralPath $PortableApp,(Join-Path $PortableRoot "install.ps1") -DestinationPath $Archive -CompressionLevel Optimal

Write-Host "[4/4] Verifying outputs..."
$ZipEntries = @(& tar.exe -tf $Archive)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the portable archive." }
if ($ZipEntries | Where-Object { $_ -match "(^|/)keys\.txt$" }) {
    throw "The portable archive contains a keys.txt file."
}
if ($ZipEntries -notcontains "install.ps1") {
    throw "The portable archive is missing install.ps1."
}
$ExeSize = [math]::Round((Get-Item -LiteralPath (Join-Path $Bundle "CartoonPrintStudio.exe")).Length / 1MB, 1)
$ZipSize = [math]::Round((Get-Item -LiteralPath $Archive).Length / 1MB, 1)
Write-Host "Executable: $Bundle\CartoonPrintStudio.exe ($ExeSize MB)"
Write-Host "Portable package: $Archive ($ZipSize MB)"
Write-Host "Copy the ZIP to each PC, extract it, then run install.ps1."
