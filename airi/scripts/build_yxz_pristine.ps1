<#
  Build the YXZ asset from the scan, changing as little as possible.

  The scan is a good model.  Rendered on its own, it is a smooth helmet
  with a badge on the forehead, a continuous dark visor with the
  character's eyes behind it, a clean mouth, five fingers on the raised
  hand, clean wings and a halo.  Every "fix" that has been applied to it
  since has taken something away with it:

    clean_yxz_shell_flakes.py   cut white gouges along every seam in the
                                 shell, and took the badge apart
    smooth_yxz_normals.py       then smoothed over what was left, so the
                                 gouges read as soft dents instead of
                                 holes

  The only thing in the scan that is genuinely broken is the wreck of an
  old halo: a wide crescent of dark blue lying across the crown of the
  head, broken into a couple of hundred pieces.  It is removed by the
  atlas rectangles it owns, so nothing that merely shares the texture
  with it is disturbed, and everything else in the scan is left exactly
  as it came out of Tripo.

  The halo the character wears now is built by build_yxz_vrm.py.

  Usage:
    pwsh scripts/build_yxz_pristine.ps1 -Tag pr1
#>

param(
  [Parameter(Mandatory = $true)][string]$Tag
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $root
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$source = Join-Path $repoRoot 'cartoon-print-studio\data\yxz_character_tripo_jpg\model\model_web.glb'
$work = Join-Path $root "docs\yxz-variants\$Tag"

New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host "=== $Tag : take the wreck of the old halo off the scan ==="
& $blender -b -P (Join-Path $root 'scripts\remove_yxz_halo_wreck.py') -- `
  --source $source `
  --output (Join-Path $work 'unwrecked.glb') 2>&1 |
  Select-String 'YXZ_WRECK|Traceback|Error'

Write-Host "=== $Tag : take the scan's own broken halo off the head ==="
& $blender -b -P (Join-Path $root 'scripts\remove_yxz_scan_halo.py') -- `
  --source (Join-Path $work 'unwrecked.glb') `
  --output (Join-Path $work 'nohalo.glb') 2>&1 |
  Select-String 'YXZ_SCAN_HALO|Traceback|Error'

Write-Host "=== $Tag : put the scan's leftover eye-bump back behind the visor ==="
& $blender -b -P (Join-Path $root 'scripts\fix_yxz_visor_bump.py') -- `
  --source (Join-Path $work 'nohalo.glb') `
  --output (Join-Path $work 'fixed.glb') 2>&1 |
  Select-String 'YXZ_BUMP|Traceback|Error'

Write-Host "=== $Tag : rig ==="
& $blender -b -P (Join-Path $root 'scripts\build_yxz_vrm.py') -- `
  --source (Join-Path $work 'fixed.glb') `
  --output (Join-Path $work 'rig.glb') 2>&1 |
  Select-String 'YXZ_BUILT|Traceback'

Write-Host "=== $Tag : vrm ==="
& $blender -b -P (Join-Path $root 'scripts\vrm_postprocess.py') -- `
  --input (Join-Path $work 'rig.glb') `
  --output (Join-Path $work 'yxz.vrm') `
  --title YXZ 2>&1 | Select-String 'YXZ_VRM_WRITTEN|Traceback'

Write-Host "=== $Tag : done (not deployed) ==="
