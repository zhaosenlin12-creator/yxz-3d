<#
  Build the YXZ asset with the least processing that still works.

  The long pipeline this replaces was an answer to a question that was
  never asked.  It was written because the character read as shattered on
  screen, and every step after the first was a guess at which piece of
  the scan was the shatter:

    strip_yxz_crown_debris.py   took the crown of the helmet off
    build_yxz_helmet.py          put a smooth synthetic cap over the hole

  Both steps are the shatter.  The crown of the helmet in the scan is
  whole -- the render of the scan's own file shows a smooth helmet with
  the badge on it -- and the debris stripper removed it because the
  crown's tiles stand a fraction of a millimetre further out from the
  middle of the head than the radius the rule used.  The raised hand went
  with them, because a hand held up beside the head is also further out
  from the middle of the head than that radius.  The cap that was then
  built over the hole was a smooth dome with no face of the scan on it,
  and a smooth dome over the helmet is exactly what the glass bubble in
  the design looks like: the character read as glassy because the
  pipeline had put a glass dome on it.

  So the chain here is the short one.  Clean the scan, take the wreck of
  the halo off it, take the litter off the shell, smooth the light on
  the shell, and rig it.  The crown of the helmet, the badge on it, the
  visor's reflection and the hand are the scan's own, and they are left
  alone.

  Usage:
    pwsh scripts/build_yxz_minimal.ps1 -Tag min1
#>

param(
  [Parameter(Mandatory = $true)][string]$Tag,
  [double]$Threshold = 0.0015,
  [double]$RepairDeg = 20,
  [double]$FlatDeg = 30,
  [double]$Weld = 0.0006,
  [double]$MaxHole = 0.03,
  [int]$NormalPasses = 3,
  [switch]$Holes,
  [switch]$Winding,
  [switch]$NoFlakes
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$source = 'C:\kaifa_senlin\pingdou\cartoon-print-studio\data\yxz_character_tripo_jpg\model\model_web.glb'
$work = Join-Path $root "docs\yxz-variants\$Tag"

New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host "=== $Tag : clean the scan ==="
& $blender -b -P (Join-Path $root 'scripts\clean_yxz_mesh.py') -- `
  --source $source `
  --output (Join-Path $work 'clean.glb') `
  --threshold $Threshold `
  --repair-deg $RepairDeg `
  --flat-deg $FlatDeg `
  --drop-loose 0 `
  --no-debris 2>&1 | Select-String 'YXZ_CLEANED|Traceback|Error'

Write-Host "=== $Tag : take the wreck of the old halo off the head ==="
& $blender -b -P (Join-Path $root 'scripts\remove_yxz_halo_wreck.py') -- `
  --source (Join-Path $work 'clean.glb') `
  --output (Join-Path $work 'unwrecked.glb') 2>&1 | Select-String 'YXZ_WRECK|Traceback|Error'

$shell = Join-Path $work 'unwrecked.glb'

if ($Holes) {
  Write-Host "=== $Tag : close the holes in the shell ==="
  & $blender -b -P (Join-Path $root 'scripts\repair_yxz_holes.py') -- `
    --source $shell `
    --output (Join-Path $work 'sewn.glb') `
    --weld $Weld `
    --max-hole $MaxHole `
    --protect-edges 40 2>&1 | Select-String 'YXZ_HOLES|Traceback|Error'
  $shell = Join-Path $work 'sewn.glb'
}

if ($Winding) {
  Write-Host "=== $Tag : turn the inside-out patches back round ==="
  & $blender -b -P (Join-Path $root 'scripts\fix_yxz_winding.py') -- `
    --source $shell `
    --output (Join-Path $work 'turned.glb') `
    --step 0.004 `
    --hops 6 2>&1 | Select-String 'WINDING|Traceback|Error'
  $shell = Join-Path $work 'turned.glb'
}

if (-not $NoFlakes) {
  Write-Host "=== $Tag : take the flakes off the shell ==="
  & $blender -b -P (Join-Path $root 'scripts\clean_yxz_shell_flakes.py') -- `
    --source $shell `
    --output (Join-Path $work 'flaked.glb') 2>&1 | Select-String 'YXZ_FLAKES|Traceback|Error'
  $shell = Join-Path $work 'flaked.glb'
}

Write-Host "=== $Tag : smooth the light on the shell ==="
& $blender -b -P (Join-Path $root 'scripts\smooth_yxz_normals.py') -- `
  --source $shell `
  --output (Join-Path $work 'lit.glb') `
  --passes $NormalPasses 2>&1 | Select-String 'NORMALS|Traceback|Error'

Write-Host "=== $Tag : rig ==="
& $blender -b -P (Join-Path $root 'scripts\build_yxz_vrm.py') -- `
  --source (Join-Path $work 'lit.glb') `
  --output (Join-Path $work 'rig.glb') 2>&1 | Select-String 'YXZ_BUILT|Traceback'

Write-Host "=== $Tag : vrm ==="
& $blender -b -P (Join-Path $root 'scripts\vrm_postprocess.py') -- `
  --input (Join-Path $work 'rig.glb') `
  --output (Join-Path $work 'yxz.vrm') `
  --title YXZ 2>&1 | Select-String 'YXZ_VRM_WRITTEN|Traceback'

Write-Host "=== $Tag : done ==="
