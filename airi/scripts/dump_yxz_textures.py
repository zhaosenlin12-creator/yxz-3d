"""
Write the asset's textures out as PNGs, so they can be looked at.

The model's marks live in the base colour atlas, and a mark that is
wrong is much easier to find in the atlas than on the model, where it is
two pixels across and turned away from the light.

    python scripts/dump_yxz_textures.py [path/to/yxz.vrm] [outDir]
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")
    outDir = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/yxz-audit/textures")
    outDir.mkdir(parents=True, exist_ok=True)

    asset = Asset(path)
    document = asset.document

    for index, image in enumerate(document.get("images", [])):
        name = image.get("name") or "image-%d" % index
        uri = image.get("uri", "")
        if uri.startswith("data:"):
            payload = base64.b64decode(uri.split(",", 1)[1])
        else:
            view = document["bufferViews"][image["bufferView"]]
            offset = view.get("byteOffset", 0)
            payload = bytes(asset.binary[offset:offset + view["byteLength"]])
        target = outDir / ("%s.png" % name)
        target.write_bytes(payload)
        print("%-34s %8d bytes -> %s" % (name, len(payload), target))


if __name__ == "__main__":
    main()
