"""Report what a built YXZ GLB actually contains for one mesh."""

from __future__ import annotations

import json
import sys

import bpy


def main() -> None:
    tail = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    glb, target = tail[0], tail[1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    obj = bpy.data.objects.get(target)
    if obj is None:
        raise SystemExit("no object " + target)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(deps)
    report = {
        "baseBounds": [[round(min(v.co[i] for v in obj.data.vertices), 4),
                        round(max(v.co[i] for v in obj.data.vertices), 4)]
                       for i in range(3)],
        "evalBounds": [[round(min(v.co[i] for v in evaluated.data.vertices), 4),
                        round(max(v.co[i] for v in evaluated.data.vertices), 4)]
                       for i in range(3)],
        "keys": [],
        "verts": len(obj.data.vertices),
    }
    if obj.data.shape_keys:
        for key in obj.data.shape_keys.key_blocks:
            report["keys"].append({
                "name": key.name,
                "value": round(key.value, 3),
                "bounds": [[round(min(v.co[i] for v in key.data), 4),
                            round(max(v.co[i] for v in key.data), 4)]
                           for i in range(3)],
            })
    print("YXZ_GLB_PROBE " + json.dumps(report))


if __name__ == "__main__":
    main()
