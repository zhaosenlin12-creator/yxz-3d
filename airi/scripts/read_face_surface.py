"""Summarise the JSON written by probe_yxz_face_surface.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "docs/yxz-rig-review/face_surface.json")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[text.index('{"glb"'):])
    print("image", data["imageSize"])
    print("samples", json.dumps(data.get("samples", {})))
    for key in ("eyeBlob", "eyeBlobSoft", "mouthBlob"):
        print(key, json.dumps(data.get(key)))
    glyph = {"white": "W", "red": "R", "navy": "N"}
    for region in ("eyeRegion", "mouthRegion"):
        print("==", region)
        for label, box in sorted(data[region]["labels"].items()):
            x0, x1, z0, z1, count = box
            cx = (x0 + x1) / 2
            cz = (z0 + z1) / 2
            print("  %-6s x[%.3f %.3f] z[%.3f %.3f] n=%-4d c=(%.4f %.4f) half=(%.4f %.4f)"
                  % (label, x0, x1, z0, z1, count, cx, cz,
                     (x1 - x0) / 2, (z1 - z0) / 2))
        grid = data[region]["frontY"]
        cells = data[region]["cells"]
        rgb = data[region]["rgb"]
        rows = sorted(grid)
        print("   brightness map (0=black .. 9=white), z increases downward")
        for x in rows:
            brightness = "".join(
                "." if cells[x][i] == "." and sum(rgb[x][i]) < 0.02
                else str(min(9, int(round(max(rgb[x][i]) * 9))))
                for i in range(len(cells[x])))
            print("   x=%6.3f %s" % (float(x), brightness))
        if region == "eyeRegion":
            print("   depth samples (x, z, frontY):")
            for x in rows[::6]:
                for i in range(0, len(grid[x]), 8):
                    print("     %.3f %.3f %s" % (float(x), 0.10 + i * 0.002,
                                               grid[x][i]))


if __name__ == "__main__":
    main()
