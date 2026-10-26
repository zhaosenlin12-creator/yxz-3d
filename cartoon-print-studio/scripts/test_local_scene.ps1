param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$SceneId = "",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

function Get-Json($url) {
    return Invoke-RestMethod -Uri $url -Method Get
}

Write-Host "[check] local trainer config"
$config = Get-Json "$BaseUrl/api/scenes/config"
if (-not $config.trainerConfigured -or $config.provider -ne "brush-local") {
    throw "Local Brush trainer is not ready: $($config | ConvertTo-Json -Compress)"
}
Write-Host "[pass] provider=$($config.provider), localTrainer=$($config.localTrainer)"

if (-not $SceneId) {
    Write-Host "[pass] Config check complete. Pass -SceneId scene_xxx to validate a result."
    exit 0
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    $scene = Get-Json "$BaseUrl/api/scenes/$SceneId"
    Write-Host "[poll] $($scene.status) - $($scene.message)"
    if ($scene.status -in @("READY", "FAILED", "WAITING_FOR_TRAINER")) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($scene.status -eq "READY") {
    if (-not $scene.result.assetUrl -or -not $scene.result.viewerUrl) {
        throw "Scene is READY but assetUrl/viewerUrl is missing"
    }
    $asset = Invoke-WebRequest -Uri ($BaseUrl + $scene.result.assetUrl) -Method Get
    Write-Host "[pass] PLY status=$($asset.StatusCode), bytes=$($scene.result.size)"
    Write-Host "[pass] viewer=$($scene.result.viewerUrl)"
    exit 0
}

if ($scene.status -eq "FAILED") {
    throw "Local scene training failed: $($scene.message)"
}

throw "Scene did not finish within $TimeoutSeconds seconds; current status: $($scene.status)"
