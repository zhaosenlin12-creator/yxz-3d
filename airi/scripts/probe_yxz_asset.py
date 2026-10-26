"""
What is actually in the YXZ asset.

Every repair to this model has to be aimed at something that can be
measured, and the asset is a stitched scan wearing a rig: one mesh for
the body, a plate for the mouth, a dish behind it, the eyes, the halo,
and the viseme shapes on the plate.  This prints that inventory --
the meshes, their materials, their morph targets, the textures and the
expressions the rig declares -- so a repair can be planned against what
is there rather than against what is assumed.

    python scripts/probe_yxz_asset.py [path/to/yxz.vrm]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


MOON_KEYS = (
    "shadeShift",
    "shadeToony",
    "rimLightingMixFactor",
    "matcapFactor",
    "parametricRimColorFactor",
    "outlineWidthMode",
    "outlineWidthFactor",
)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
    asset = Asset(path)
    document = asset.document

    print("ASSET", path, "%.1f MB" % (path.stat().st_size / 1e6))

    print("")
    print("MESHES")
    for index, mesh in enumerate(document.get("meshes", [])):
        for primitive in mesh.get("primitives", []):
            material = document["materials"][primitive["material"]]
            mtoon = material.get("extensions", {}).get("VRMC_materials_mtoon", {})
            colour = material.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
            print("  [%d] %-42s verts %-6d tris %-6d mat %s" % (
                index,
                mesh.get("name", "?"),
                document["accessors"][primitive["attributes"]["POSITION"]]["count"],
                document["accessors"][primitive["indices"]]["count"] // 3,
                material.get("name", "?"),
            ))
            print("       base %s  colour %s  shade %s  emissive %s" % (
                [round(v, 3) for v in colour[:3]],
                [round(v, 3) for v in mtoon.get("colorFactor", [0, 0, 0])[:3]],
                [round(v, 3) for v in mtoon.get("shadeColorFactor", [0, 0, 0])[:3]],
                [round(v, 3) for v in mtoon.get("emissiveFactor", [0, 0, 0])[:3]],
            ))
            for target in mesh.get("extras", {}).get("targetNames", []):
                print("       morph %s" % target)

    print("")
    print("TEXTURES")
    for index, texture in enumerate(document.get("textures", [])):
        source = texture.get("source")
        image = document["images"][source] if source is not None else {}
        print("  [%d] %-30s %s  %s" % (
            index,
            image.get("name", "?"),
            image.get("mimeType", "?"),
            image.get("uri", "(in buffer)"),
        ))

    print("")
    print("MATERIALS")
    for index, material in enumerate(document.get("materials", [])):
        mtoon = material.get("extensions", {}).get("VRMC_materials_mtoon", {})
        print("  [%d] %-30s doubleSided %s" % (
            index, material.get("name", "?"), material.get("doubleSided", False)))
        if mtoon:
            summary = {key: mtoon[key] for key in MOON_KEYS if key in mtoon}
            print("       %s" % json.dumps(summary))

    vrm = document.get("extensions", {}).get("VRMC_vrm", {})
    print("")
    print("EXPRESSIONS")
    for name, value in vrm.get("expressions", {}).items():
        print("  %-12s %s" % (name, json.dumps(value)[:120]))


if __name__ == "__main__":
    main()
