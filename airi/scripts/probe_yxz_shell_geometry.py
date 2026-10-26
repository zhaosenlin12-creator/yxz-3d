"""Measure whether the YXZ shell can support an MToon outline at all.

An MToon outline is a second pass that draws the *back* faces of a mesh
pushed out along the vertex normals.  That only produces a silhouette line
when the mesh is a closed shell whose triangles are all wound the same way
round: every back face then sits behind the front face that hides it, and
only the ones that overhang the silhouette survive.

The body comes out of Tripo as a merge of many scanned blobs, so the one
property the technique depends on is exactly the one a merge can break.
When the winding is inconsistent, "back faces" also appear on the side
facing the camera, get pushed towards it, win the depth test and paint flat
ink over the character -- a grey veil rather than a line.  This measures the
winding, the normal lengths and the degenerate triangles so the decision to
keep or drop the outline rests on numbers instead of on how the render looks.

Usage: python scripts/probe_yxz_shell_geometry.py <model.glb>
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb  # noqa: E402


COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
             5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(document, binary, index):
    accessor = document["accessors"][index]
    fmt, size = COMPONENT[accessor["componentType"]]
    components = COMPONENTS[accessor["type"]]
    # glTF allows a byteStride, but every element still starts on a 4-byte
    # boundary within the view.
    values = []
    view = document["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or (size * components)
    for i in range(accessor["count"]):
        values.append(struct.unpack_from("<" + fmt * components,
                                        binary, base + i * stride))
    return values


def main():
    source = (sys.argv[1] if len(sys.argv) > 1
              else "docs/yxz-rig-review/yxz_rig_test.glb")
    document, binary = read_glb(source)

    # The exported asset faces +Z, so a camera in front looks down -Z: a
    # triangle is front-facing when its geometric normal points back at +Z.
    view_dir = (0.0, 0.0, 1.0)

    for mesh in document.get("meshes", []):
        for part, primitive in enumerate(mesh.get("primitives", [])):
            if primitive.get("mode", 4) != 4:
                continue
            attributes = primitive["attributes"]
            positions = read_accessor(document, binary, attributes["POSITION"])
            indices = read_accessor(document, binary, primitive["indices"])
            has_normals = "NORMAL" in attributes
            normals = (read_accessor(document, binary, attributes["NORMAL"])
                       if has_normals else [])

            front = back = degenerate = 0
            agrees = disagrees = 0
            disagreement_area = 0.0
            total_area = 0.0
            for i in range(0, len(indices), 3):
                a, b, c = indices[i][0], indices[i + 1][0], indices[i + 2][0]
                pa, pb, pc = positions[a], positions[b], positions[c]
                ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
                vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                area = (nx * nx + ny * ny + nz * nz) ** 0.5
                if area <= 1e-12:
                    degenerate += 1
                    continue
                total_area += area

                # The decisive test.  Back-face culling follows the winding
                # while the outline offset follows the vertex normal, so a
                # triangle wound against its own normal is exactly the case
                # that gets culled from the surface pass yet pushed towards
                # the camera by the outline pass.  Weight by area so a handful
                # of slivers cannot dominate the number.
                if has_normals:
                    mx = (normals[a][0] + normals[b][0] + normals[c][0]) / 3.0
                    my = (normals[a][1] + normals[b][1] + normals[c][1]) / 3.0
                    mz = (normals[a][2] + normals[b][2] + normals[c][2]) / 3.0
                    if nx * mx + ny * my + nz * mz > 0:
                        agrees += 1
                    else:
                        disagrees += 1
                        disagreement_area += area

                if (nx * view_dir[0] + ny * view_dir[1] + nz * view_dir[2]) / area > 0:
                    front += 1
                else:
                    back += 1
            total = front + back
            wound = agrees + disagrees

            # Normal quality drives the outline offset directly: the shader
            # multiplies by length(transformedNormal), so a zero or wild
            # normal means a missing or exploding ink line.
            zero_normals = 0
            non_unit = 0
            for n in normals:
                length = sum(component * component for component in n) ** 0.5
                if length < 1e-6:
                    zero_normals += 1
                elif length > 1.05 or length < 0.95:
                    non_unit += 1

            print(json.dumps({
                "mesh": mesh.get("name"),
                "part": part,
                "vertices": len(positions),
                "triangles": total,
                "frontFacing": front,
                "backFacing": back,
                "frontRatio": round(front / total, 4) if total else None,
                "degenerate": degenerate,
                "windingAgreesWithNormals": agrees,
                "windingDisagrees": disagrees,
                "disagreementAreaRatio": (round(disagreement_area / total_area, 4)
                                          if total_area else None),
                "normalsMissing": not has_normals,
                "zeroNormals": zero_normals,
                "nonUnitNormals": non_unit,
            }))


if __name__ == "__main__":
    main()
