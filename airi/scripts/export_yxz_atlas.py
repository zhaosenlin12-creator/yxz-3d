"""Save the model's own texture out as a picture.

Whether a mark on the character is a hole in the shell or a mark in the
paint is the difference between repairing geometry and repairing a
picture, and the two are fixed in completely different places.  The
atlas is the only way to tell them apart without guessing, so it is
written out where it can be looked at.

Usage:
  blender -b -P scripts/export_yxz_atlas.py -- \
    --source <glb> --out <dir> [--name Color]
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    source = Path(value_after("--source"))
    out = Path(value_after("--out"))
    name = value_after("--name", "")
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))

    for image in bpy.data.images:
        if name and not image.name.startswith(name):
            continue
        image.filepath_raw = str(out / (image.name + ".png"))
        image.file_format = "PNG"
        image.save()
        print("YXZ_ATLAS " + image.filepath_raw)


if __name__ == "__main__":
    main()
