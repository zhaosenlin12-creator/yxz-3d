$ErrorActionPreference = 'Stop'

$port = 5199
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$workdir = Join-Path $root 'apps\stage-web'
$runDir = Join-Path $root '.run'
$stdout = Join-Path $runDir 'stage-web-5199.out.log'
$stderr = Join-Path $runDir 'stage-web-5199.err.log'
$corepackCommand = (Get-Command 'corepack.cmd' -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

try {
  $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/yxz-avatar" -TimeoutSec 5
  if ($response.StatusCode -eq 200) {
    Write-Output "YXZ avatar page is already served on port $port."
    exit 0
  }
}
catch {
}

Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue

$process = Start-Process -FilePath $corepackCommand `
  -ArgumentList 'pnpm', 'exec', 'vite', '--host', '--port', $port `
  -WorkingDirectory $workdir `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -WindowStyle Hidden `
  -PassThru

Write-Output "Wrapper PID: $($process.Id)"

for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 1
  try {
    $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/yxz-avatar" -TimeoutSec 4
    if ($response.StatusCode -eq 200) {
      Write-Output "Ready after $($i + 1)s on http://127.0.0.1:$port/yxz-avatar"
      exit 0
    }
  }
  catch {
  }
}

Write-Output 'The dev server did not become ready in time.'
if (Test-Path $stdout) {
  Write-Output '--- stdout ---'
  Get-Content $stdout -Tail 40
}
if (Test-Path $stderr) {
  Write-Output '--- stderr ---'
  Get-Content $stderr -Tail 40
}
exit 1
