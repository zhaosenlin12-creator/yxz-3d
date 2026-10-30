<#
  Build one variant of the YXZ asset and capture it.

  The rebuild is a five step chain -- clean the scan, close the holes in
  its shell, turn its inside-out patches back round, rig it, wrap it as a
  VRM -- and every step takes a couple of minutes, so a sweep over the
  normal smoothing angle is scripted rather than typed out by hand.

  The winding step is what stops the character reading as shattered.  A
  scan is stitched from overlapping pieces and some of them were kept
  inside out; the material is single sided, so a face turned away from
  the camera is not drawn and the piece it belongs to stops existing on
  screen.  Closing holes cannot help, because there is nothing missing
  there -- the surface is present and pointing the wrong way.

  Usage:
    pwsh scripts/build_yxz_variant.ps1 -Angle 70 -Tag angle70
#>

param(
  [Parameter(Mandatory = $true)][string]$Tag,
  [double]$Threshold = 0.0015,
  [double]$RepairDeg = 20,
  [double]$FlatDeg = 30,
  [double]$Weld = 0.0006,
  [double]$MaxHole = 0.03,
  [switch]$Prune,
  [int]$DropLoose = 0,
  [double]$WindingStep = 0.004,
  [int]$WindingHops = 6,
  [int]$NormalPasses = 3,
  # The radius the debris stripper takes off the crown at.  It was 0.293,
  # which left a band of the old torn shell standing a hair proud of the
  # helmet between the visor and the rebuilt cap; 0.2905 takes that band
  # with it and leaves the visor edge alone.
  [double]$DebrisRadius = 0.2905,
  [string]$HeadProtect = '-0.30,-0.32,0.20,0.30,0.32,0.45',
  [string]$CrownBox = '-0.26,-0.27,0.26,0.02,0.02,0.40',
  # Keep the crown of the helmet exactly as the scan made it.
  #
  # The scan has a clear bubble over the head and the crown of the
  # helmet under it is the scan's own face, with the badge on it.  The
  # bubble is what makes the character read as glassy, and taking the
  # bubble off is enough to fix that.  The crown was being rebuilt as
  # well, which put a smooth cap where a face had been -- a cap with
  # no face of the scan on it is a smooth dome, so it read as a bubble
  # again, and it took the badge with it.
  [switch]$KeepCrown
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $root
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$source = Join-Path $repoRoot 'cartoon-print-studio\data\yxz_character_tripo_jpg\model\model_web.glb'
$work = Join-Path $root "docs\yxz-variants\$Tag"

New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host "=== $Tag : clean (repair $RepairDeg) ==="
& $blender -b -P (Join-Path $root 'scripts\clean_yxz_mesh.py') -- `
  --source $source `
  --output (Join-Path $work 'clean.glb') `
  --threshold $Threshold `
  --repair-deg $RepairDeg `
  --flat-deg $FlatDeg `
  --drop-loose $DropLoose `
  --no-debris 2>&1 | Select-String 'YXZ_CLEANED|Traceback|Error'

Write-Host "=== $Tag : take the wreck of the old halo off the head ==="
& $blender -b -P (Join-Path $root 'scripts\remove_yxz_halo_wreck.py') -- `
  --source (Join-Path $work 'clean.glb') `
  --output (Join-Path $work 'unwrecked.glb') 2>&1 | Select-String 'YXZ_WRECK|Traceback|Error'

if ($Prune) {
  Write-Host "=== $Tag : take the dust and the torn scraps off the shell ==="
  & $blender -b -P (Join-Path $root 'scripts\prune_yxz_shells.py') -- `
    --source (Join-Path $work 'unwrecked.glb') `
    --output (Join-Path $work 'pruned.glb') `
    --crown-box0 $CrownBox `
    --apply 2>&1 | Select-String 'YXZ_PRUNE|YXZ_PRUNED|Traceback|Error'
  $shell = Join-Path $work 'pruned.glb'
} else {
  # The prune is off by default.  It takes the small shells off the scan,
  # and the small shells are not lying on the surface of a bigger piece:
  # they are the surface.  Taking them off left the character as a sieve,
  # with a hole through the visor, the star on the forehead in pieces and
  # the rim of the helmet torn open, which is where the shattered look
  # on screen came from.  The scan's own surface, welded and with the
  # wreck of the old halo taken off it, is already clean.
  $shell = Join-Path $work 'unwrecked.glb'
}

Write-Host "=== $Tag : close the holes in the shell ==="
& $blender -b -P (Join-Path $root 'scripts\repair_yxz_holes.py') -- `
  --source $shell `
  --output (Join-Path $work 'sewn.glb') `
  --weld $Weld `
  --max-hole $MaxHole `
  --protect-edges 40 `
  --protect0 $HeadProtect 2>&1 | Select-String 'YXZ_HOLES|Traceback|Error'

Write-Host "=== $Tag : turn the inside-out patches back round ==="
& $blender -b -P (Join-Path $root 'scripts\fix_yxz_winding.py') -- `
  --source (Join-Path $work 'sewn.glb') `
  --output (Join-Path $work 'turned.glb') `
  --step $WindingStep `
  --hops $WindingHops 2>&1 | Select-String 'WINDING|Traceback|Error'

if (-not $KeepCrown) {
Write-Host "=== $Tag : take the litter off the crown of the helmet ==="
# This runs after the holes are closed and the winding is right, and not
# before.  Run early it reads the crown of the head, which is still a
# tangle of loose pieces at that point, as if it were debris, and takes
# the helmet with it.  Run late the helmet is a helmet, and what is left
# over it is the litter: the sheets of the clear bubble that stood over it
# and shattered, the strips of shell that were torn off and never taken
# away, and the crumbs of every size.
#
# The test is how far out from the middle of the head a piece starts.
# Nothing that belongs to the helmet stands off the dome by more than a
# millimetre, so the pieces that do are the litter, and the crown is left
# as the smooth white shell the design is.
#
# (An earlier revision ran `clean_yxz_slivers.py` here instead.  That
# script takes off the slivers of shell that stand proud of the surface,
# and on this scan the rim of the helmet is a sliver: it took the rim with
# them and left the head with a torn-open edge, which is worse than the
# litter it was meant to remove.)
& $blender -b -P (Join-Path $root 'scripts\strip_yxz_crown_debris.py') -- `
  --source (Join-Path $work 'turned.glb') `
  --output (Join-Path $work 'stripped.glb') `
  --radius $DebrisRadius 2>&1 | Select-String 'YXZ_DEBRIS|Traceback|Error'

Write-Host "=== $Tag : put the crown of the helmet back ==="
# The crown of the helmet is the one piece of the scan that was cut out
# rather than scanned, and the cut was never closed, so the top of the
# head is a long ragged gash with the sheet of the glass bubble lying
# across it.  Nothing else in the pipeline can close it: the hole repair
# refuses a tear that long, and a tear that long fanned to a single point
# is a hedgehog of needles standing off the crown.
#
# So the crown is rebuilt instead.  The bubble goes, the torn blades of
# shell go, and what is left is capped with a smooth piece of the same
# sphere the helmet is built on.  The cap is set a couple of millimetres
# outside the shell and tapered back down to it over a wide band, so the
# join is a soft gradient rather than a step with a line along it -- the
# earlier revision of this put the cap four millimetres proud and tapered
# it over two degrees, and the result had a hard seam straight across the
# forehead.
& $blender -b -P (Join-Path $root 'scripts\build_yxz_helmet.py') -- `
  --source (Join-Path $work 'stripped.glb') `
  --output (Join-Path $work 'crowned.glb') `
  --crown-lift 0.002 `
  --rim-fall 9.0 2>&1 | Select-String 'YXZ_HELMET|Traceback|Error'
} else {
Write-Host "=== $Tag : take the glass bubble off the head ==="
#
# The bubble is the skin of geometry that stands clear of the sphere the
# helmet is built on.  It is taken off face by face, because the scan
# welded the bubble to the helmet in places and there is no shell that
# is only bubble.  The badge on the forehead stands clear by about as
# much as the bubble did, so it is kept by where it is.
#
# What is left is the scan's own crown, with the badge on it.
& $blender -b -P (Join-Path $root 'scripts\remove_yxz_bubble.py') -- `
  --source (Join-Path $work 'turned.glb') `
  --output (Join-Path $work 'crowned.glb') 2>&1 | Select-String 'YXZ_BUBBLE|Traceback|Error'
}

Write-Host "=== $Tag : take the flakes off the shell ==="
# The scan is a mosaic of several hundred separate pieces, and a piece
# that lies *on* another one is a second copy of a patch of it a fraction
# of a millimetre off.  The depth test cannot decide between the two, so
# the shell comes out scratched with dark hairline marks and speckled with
# the white of the copy -- which is what made the character read as
# shattered rather than as whole.
#
# This runs after the crown has been rebuilt, because the crown rebuild is
# what leaves the last of the litter exposed, and it runs before the
# normals are smoothed, because a sweep leaves edges behind that the
# smoothing then has to settle.
& $blender -b -P (Join-Path $root 'scripts\clean_yxz_shell_flakes.py') -- `
  --source (Join-Path $work 'crowned.glb') `
  --output (Join-Path $work 'flaked.glb') 2>&1 | Select-String 'YXZ_FLAKES|Traceback|Error'

Write-Host "=== $Tag : smooth the light on the shell ==="
& $blender -b -P (Join-Path $root 'scripts\smooth_yxz_normals.py') -- `
  --source (Join-Path $work 'flaked.glb') `
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

Write-Host "=== $Tag : deploy + capture ==="
Copy-Item (Join-Path $work 'yxz.vrm') `
  (Join-Path $root 'packages\stage-ui-three\src\assets\vrm\models\yxz.vrm') -Force
node (Join-Path $root 'scripts\probe_yxz_face_ab.mjs') 'http://localhost:5199' `
  (Join-Path $root "docs\yxz-variants\$Tag\shots") 2>&1 | Select-String 'SHOT|PAGE_ERRORS'

Write-Host "=== $Tag : done ==="


