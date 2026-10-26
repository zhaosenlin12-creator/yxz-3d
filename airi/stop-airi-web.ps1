$port = 5183

$listenerPids = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique

$listenerTargets = @()
if ($listenerPids) {
  $listenerTargets = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -in $listenerPids -and $_.CommandLine -like '*\apps\stage-web*'
  }
}

$processTargets = Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -like '*\apps\stage-web*' -and (
      $_.CommandLine -like '*vite*' -or
      $_.CommandLine -like '*pnpm exec vite*' -or
      $_.CommandLine -like '*cmd.exe /c pnpm exec vite*'
    )
  }

$targets = @(@($listenerTargets) + @($processTargets)) | Sort-Object ProcessId -Unique

if (-not $targets) {
  Write-Output "No AIRI Stage Web process for port $port was found."
  exit 0
}

$targets | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output "Stopped PID $($_.ProcessId)"
}
