"""Print one mesh entry from a GLB's JSON chunk."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def main() -> None:
    path = sys.argv[-1]
    wanted = sys.argv[-2]
    raw = Path(path).read_bytes()
    magic, _version, length = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise SystemExit("not a glb")
    offset = 12
    chunks = {}
    while offset < length:
        size, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        chunks[kind] = raw[offset:offset + size]
        offset += size
    doc = json.loads(chunks[0x4E4F534A].decode("utf-8"))
    for mesh in doc.get("meshes", []):
        if mesh.get("name") == wanted:
            print(json.dumps(mesh, indent=1)[:6000])
            return
    print("meshes: " + ", ".join(m.get("name", "?") for m in doc.get("meshes", [])))


if __name__ == "__main__":
    main()
