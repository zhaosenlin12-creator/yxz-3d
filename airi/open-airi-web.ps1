$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root '.run'
$profileDir = Join-Path $runDir 'edge-profile'
$cacheDir = Join-Path $runDir 'edge-cache'
$url = 'http://localhost:5183/'

New-Item -ItemType Directory -Force -Path $runDir, $profileDir, $cacheDir | Out-Null

$edgeCandidates = @(
  (Get-Command 'msedge.exe' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
) | Where-Object { $_ -and (Test-Path $_) }

$edge = $edgeCandidates | Select-Object -First 1
if (-not $edge) {
  throw 'Microsoft Edge not found.'
}

Start-Process -FilePath $edge `
  -ArgumentList @(
    "--user-data-dir=$profileDir",
    "--disk-cache-dir=$cacheDir",
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-sync',
    $url
  ) `
  -WindowStyle Maximized | Out-Null

Write-Output "Opened AIRI in isolated Edge profile: $url"
Write-Output "Profile: $profileDir"
