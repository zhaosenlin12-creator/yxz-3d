$ErrorActionPreference = 'Stop'

$port = 5183
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$workdir = Join-Path $root 'apps\stage-web'
$runDir = Join-Path $root '.run'
$stdout = Join-Path $runDir 'stage-web-5183.out.log'
$stderr = Join-Path $runDir 'stage-web-5183.err.log'
$corepackCommand = (Get-Command 'corepack.cmd' -ErrorAction Stop).Source

function Get-ListenerProcess {
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

  if (-not $listeners) {
    return @()
  }

  return Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $listeners }
}

function Test-AiriWeb {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "http://localhost:$port" -TimeoutSec 5
    return $response.Content -match '<title>AIRI</title>'
  }
  catch {
    return $false
  }
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$listenerProcesses = Get-ListenerProcess
if ($listenerProcesses) {
  $airiListener = $listenerProcesses | Where-Object { $_.CommandLine -like '*D:\kaifa\airi\apps\stage-web*' }
  if ($airiListener -and (Test-AiriWeb)) {
    Write-Output "AIRI Stage Web is already running on port $port."
    Write-Output "Open: http://localhost:$port/"
    exit 0
  }

  $foreignListener = $listenerProcesses | Select-Object -First 1
  if (-not $airiListener) {
    Write-Output "Port $port is occupied by another process:"
    Write-Output $foreignListener.CommandLine
    exit 1
  }
}

$staleProcesses = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*D:\kaifa\airi\apps\stage-web*' -and $_.CommandLine -like '*vite*' }

$staleProcesses | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue

$process = Start-Process -FilePath $corepackCommand `
  -ArgumentList 'pnpm', 'exec', 'vite', '--host', '--port', $port `
  -WorkingDirectory $workdir `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -WindowStyle Hidden `
  -PassThru

for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Seconds 1
  if (Test-AiriWeb) {
    Write-Output "Started AIRI Stage Web. Wrapper PID: $($process.Id)"
    Write-Output "Open: http://localhost:$port/"
    Write-Output "Stdout log: $stdout"
    Write-Output "Stderr log: $stderr"
    exit 0
  }
}

Write-Output 'AIRI Stage Web did not become ready in time.'
if (Test-Path $stdout) {
  Write-Output '--- stdout ---'
  Get-Content $stdout -Tail 80
}
if (Test-Path $stderr) {
  Write-Output '--- stderr ---'
  Get-Content $stderr -Tail 80
}
exit 1
