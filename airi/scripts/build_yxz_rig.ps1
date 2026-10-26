<#
  Re-rig an already cleaned shell and wrap it as a VRM.

  The clean/repair/smooth chain is the slow part -- half an hour of
  Blender -- and none of it touches the rig.  The rig is where the halo
  is built, so when only the halo changes there is no reason to walk
  the whole chain again: the shell that came out of the last chain is
  still the right shell.

  Usage:
    pwsh scripts/build_yxz_rig.ps1 -Tag v10 -Source docs\yxz-variants\v10\lit.glb
#>

param(
  [Parameter(Mandatory = $true)][string]$Tag,
  [Parameter(Mandatory = $true)][string]$Source
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$work = Join-Path $root "docs\yxz-variants\$Tag"

Write-Host "=== $Tag : rig $Source ==="
& $blender -b -P (Join-Path $root 'scripts\build_yxz_vrm.py') -- `
  --source $Source `
  --output (Join-Path $work 'rig.glb') 2>&1 |
  Select-String 'YXZ_BUILT|YXZ_HALO_REPORT|Traceback|Error'

Write-Host "=== $Tag : vrm ==="
& $blender -b -P (Join-Path $root 'scripts\vrm_postprocess.py') -- `
  --input (Join-Path $work 'rig.glb') `
  --output (Join-Path $work 'yxz.vrm') `
  --title YXZ 2>&1 | Select-String 'YXZ_VRM_WRITTEN|Traceback'

Write-Host "=== $Tag : deploy ==="
Copy-Item (Join-Path $work 'yxz.vrm') `
  (Join-Path $root 'packages\stage-ui-three\src\assets\vrm\models\yxz.vrm') -Force
Write-Host "=== $Tag : done ==="
