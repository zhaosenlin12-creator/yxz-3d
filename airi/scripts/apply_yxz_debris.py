"""
 * Take the loose sheets off the face, and write the result out.
 *
 * `remove_yxz_debris.py` knows which pieces of the scan were folded over
 * and left lying on the cheek; this runs it and saves, so the step can
 * be used on its own from a shell.
 *
 * Usage:
 *   blender -b -P scripts/apply_yxz_debris.py -- --source <glb> --output <glb>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remove_yxz_debris import remove_debris  # noqa: E402


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


source = Path(value_after("--source"))
output = Path(value_after("--output"))
output.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
body = max(
    (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
    key=lambda obj: len(obj.data.vertices),
)
print("YXZ_DEBRIS_NOW " + json.dumps(remove_debris(body.data)))
bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")

