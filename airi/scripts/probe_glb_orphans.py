"""Report which JSON objects keep otherwise-unused buffer views alive."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glb_json import read_glb  # noqa: E402


def main(argv):
    document, _binary = read_glb(argv[0])
    views = document.get("bufferViews", [])
    used = set()

    for index, accessor in enumerate(document.get("accessors", [])):
        if "bufferView" in accessor:
            used.add(accessor["bufferView"])
            print(f"accessor {index} -> view {accessor['bufferView']} "
                  f"count={accessor.get('count')} type={accessor.get('type')}")
    for index, image in enumerate(document.get("images", [])):
        if "bufferView" in image:
            used.add(image["bufferView"])
            print(f"image {index} -> view {image['bufferView']}")
    for index, skin in enumerate(document.get("skins", [])):
        if "inverseBindMatrices" in skin:
            used.add(skin["inverseBindMatrices"])
            print(f"skin {index} ibm -> view {skin['inverseBindMatrices']}")
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for prim_index, primitive in enumerate(mesh.get("primitives", [])):
            for name, extension in primitive.get("extensions", {}).items():
                if isinstance(extension, dict) and "bufferView" in extension:
                    used.add(extension["bufferView"])
                    print(f"mesh {mesh_index} prim {prim_index} {name} "
                          f"-> view {extension['bufferView']}")

    print("--- orphans ---")
    total = 0
    for index, view in enumerate(views):
        if index in used:
            continue
        length = view.get("byteLength", 0)
        total += length
        print(f"view {index} length={length} unused")
    print(f"total orphan bytes: {total}")


if __name__ == "__main__":
    main(sys.argv[1:])
