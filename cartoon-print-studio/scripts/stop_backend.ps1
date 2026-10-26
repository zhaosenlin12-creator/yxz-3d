$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "logs\backend.pid"
if (Test-Path $pidFile) {
    $procId = (Get-Content $pidFile -Raw).Trim()
    if ($procId) {
        Get-Process -Id $procId -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -like "*$root*" -or $_.ProcessName -like "*python*"
        } | Stop-Process -Force
    }
    Remove-Item $pidFile -Force
}
$leftovers = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$root*" }
if ($leftovers) {
    $leftovers | Stop-Process -Force
    Write-Host "[backend] stopped $($leftovers.Count) leftover process(es) from this install"
} else {
    Write-Host "[backend] stopped"
}
