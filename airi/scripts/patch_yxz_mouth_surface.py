"""Rebuild the YXZ mouth plate so that it *is* the face's own surface.

The scan the character was built from has one clean hand-painted red
smile, and on its own it is the best thing about the face.  A mouth was
then added on top of it, to give the character somewhere to put a lip
shape, and that addition is what made the face look broken:

   * the plate was exported without a texture, so it came out as a flat
     grey oval pasted over the muzzle;
   * it was a coarse grid -- forty-eight segments and five rings -- so
     its own faces cut across the scan's relief and the real smile came
     through them in shards;
   * and its normals were the normals of that coarse grid rather than
     the normals of the face it was sitting on, so the oval shaded
     differently from the surface around it and read as a sticker.

The plate does not have to be a separate surface.  Everything it has to
do it can do by being the face: the same texture coordinates and the
same normals as the face underneath it, lifted a third of a millimetre
so that it is not fighting with the face for the same pixels.  A plate
built that way is invisible -- the eye cannot see where it starts or
stops, because the paint on it is the paint that is already there.

The hole in the middle of it is what does the talking.  The hole keeps
the nine viseme shapes the plate already had, and a dark dish behind it
is what shows through when the hole opens.

The script patches the deployed VRM as a file: the rig, the crown, the
eyes and the halo are not touched.

    python scripts/patch_yxz_mouth_surface.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np


# --- the glTF container ----------------------------------------------------

COMPONENT = {
    5120: "<i1",
    5121: "<u1",
    5122: "<i2",
    5123: "<u2",
    5125: "<u4",
    5126: "<f4",
}
COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class Asset:
    """A glTF binary read whole, and written back whole."""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        magic, version, length = struct.unpack_from("<III", raw, 0)
        if magic != 0x46546C67:
            raise ValueError("not a glTF binary")
        self.version = version
        self.chunks: list[tuple[int, bytes]] = []
        offset = 12
        while offset < length:
            size, kind = struct.unpack_from("<II", raw, offset)
            self.chunks.append((kind, raw[offset + 8:offset + 8 + size]))
            offset += 8 + size
        self.document = json.loads(
            next(data for kind, data in self.chunks if kind == 0x4E4F534A).decode("utf-8"))
        self.binary = bytearray(
            next((data for kind, data in self.chunks if kind == 0x004E4942), b""))

    def accessor(self, index: int) -> np.ndarray:
        spec = self.document["accessors"][index]
        count = COUNT[spec["type"]]
        dtype = np.dtype(COMPONENT[spec["componentType"]])
        out = np.zeros((spec["count"], count), dtype=dtype)
        if "bufferView" in spec:
            view = self.document["bufferViews"][spec["bufferView"]]
            base = view.get("byteOffset", 0) + spec.get("byteOffset", 0)
            stride = view.get("byteStride") or count * dtype.itemsize
            raw = bytes(self.binary)
            for row in range(spec["count"]):
                out[row] = np.frombuffer(
                    raw, dtype=dtype, count=count, offset=base + row * stride)
        # A sparse accessor starts at zero and only says what changed.
        sparse = spec.get("sparse")
        if sparse:
            index_view = self.document["bufferViews"][sparse["indices"]["bufferView"]]
            index_dtype = np.dtype(COMPONENT[sparse["indices"]["componentType"]])
            index_base = index_view.get("byteOffset", 0) + \
                sparse["indices"].get("byteOffset", 0)
            value_view = self.document["bufferViews"][sparse["values"]["bufferView"]]
            value_base = value_view.get("byteOffset", 0) + \
                sparse["values"].get("byteOffset", 0)
            raw = bytes(self.binary)
            for row in range(sparse["count"]):
                index = int(np.frombuffer(
                    raw, dtype=index_dtype, count=1, offset=index_base + row * index_dtype.itemsize)[0])
                out[index] = np.frombuffer(
                    raw, dtype=dtype, count=count, offset=value_base + row * count * dtype.itemsize)
        return out

    def append_view(self, data: bytes) -> int:
        while len(self.binary) % 4:
            self.binary.append(0)
        offset = len(self.binary)
        self.binary.extend(data)
        self.document.setdefault("bufferViews", []).append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        })
        return len(self.document["bufferViews"]) - 1

    def add_accessor(self, array: np.ndarray, kind: str,
                     target: int | None = None) -> int:
        array = np.ascontiguousarray(array)
        if array.dtype == np.float64:
            array = array.astype(np.float32)
        elif array.dtype == np.int64:
            array = array.astype(np.uint32)
        component = {
            ("f", 4): 5126,
            ("u", 1): 5121, ("u", 2): 5123, ("u", 4): 5125,
            ("i", 1): 5120, ("i", 2): 5122, ("i", 4): 5125,
        }[(array.dtype.kind, array.dtype.itemsize)]
        view = self.append_view(array.tobytes())
        spec = {
            "bufferView": view,
            "componentType": component,
            "count": int(array.shape[0]),
            "type": kind,
        }
        if target is not None:
            spec["target"] = target
        self.document.setdefault("accessors", []).append(spec)
        return len(self.document["accessors"]) - 1

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = json.dumps(self.document, separators=(",", ":")).encode("utf-8")
        while len(document) % 4:
            document += b" "
        binary = bytes(self.binary)
        while len(binary) % 4:
            binary += b"\0"
        total = 12 + 8 + len(document) + (8 + len(binary) if binary else 0)
        out = bytearray()
        out.extend(struct.pack("<III", 0x46546C67, self.version, total))
        out.extend(struct.pack("<II", len(document), 0x4E4F534A))
        out.extend(document)
        if binary:
            out.extend(struct.pack("<II", len(binary), 0x004E4942))
            out.extend(binary)
        path.write_bytes(bytes(out))


# --- geometry --------------------------------------------------------------


def closest_on_triangle(points: np.ndarray, a: np.ndarray, b: np.ndarray,
                        c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The closest point on one triangle, for every point given.

    Ericson's region test, vectorised over the points.
    """
    ab = b - a
    ac = c - a
    ap = points - a
    d1 = (ab * ap).sum(1)
    d2 = (ac * ap).sum(1)
    bp = points - b
    d3 = (ab * bp).sum(1)
    d4 = (ac * bp).sum(1)
    cp = points - c
    d5 = (ab * cp).sum(1)
    d6 = (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    total = va + vb + vc
    safe = np.where(np.abs(total) < 1e-20, 1.0, total)
    v = vb / safe
    w = vc / safe
    result = a + np.outer(v, ab) + np.outer(w, ac)

    at_a = (d1 <= 0) & (d2 <= 0)
    at_b = (d3 >= 0) & (d4 <= d3)
    at_c = (d6 >= 0) & (d5 <= d6)
    result = np.where(at_a[:, None], a, result)
    result = np.where(at_b[:, None], b, result)
    result = np.where(at_c[:, None], c, result)

    edge_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t_ab = d1 / np.where(np.abs(d1 - d3) < 1e-20, 1.0, d1 - d3)
    result = np.where(edge_ab[:, None], a + t_ab[:, None] * ab, result)

    edge_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t_ac = d2 / np.where(np.abs(d2 - d6) < 1e-20, 1.0, d2 - d6)
    result = np.where(edge_ac[:, None], a + t_ac[:, None] * ac, result)

    edge_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t_bc = (d4 - d3) / np.where(
        np.abs((d4 - d3) + (d5 - d6)) < 1e-20, 1.0, (d4 - d3) + (d5 - d6))
    result = np.where(edge_bc[:, None], b + t_bc[:, None] * (c - b), result)
    return result, np.linalg.norm(points - result, axis=1)


def barycentric(point: np.ndarray, a: np.ndarray, b: np.ndarray,
                c: np.ndarray) -> np.ndarray:
    """The barycentric weights of a point in a triangle's plane."""
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = (v0 * v0).sum(-1)
    d01 = (v0 * v1).sum(-1)
    d11 = (v1 * v1).sum(-1)
    d20 = (v2 * v0).sum(-1)
    d21 = (v2 * v1).sum(-1)
    denom = d00 * d11 - d01 * d01
    safe = np.where(np.abs(denom) < 1e-24, 1.0, denom)
    v = (d11 * d20 - d01 * d21) / safe
    w = (d00 * d21 - d01 * d20) / safe
    return np.stack([1.0 - v - w, v, w], axis=-1)


class Face:
    """The body mesh, and the questions one can ask of it."""

    def __init__(self, asset: Asset, mesh_index: int):
        primitive = asset.document["meshes"][mesh_index]["primitives"][0]
        attributes = primitive["attributes"]
        self.positions = asset.accessor(attributes["POSITION"]).astype(np.float64)
        self.normals = asset.accessor(attributes["NORMAL"]).astype(np.float64)
        self.uvs = asset.accessor(attributes["TEXCOORD_0"]).astype(np.float64)
        self.joints = asset.accessor(attributes["JOINTS_0"])
        self.weights = asset.accessor(attributes["WEIGHTS_0"])
        indices = asset.accessor(primitive["indices"]).reshape(-1).astype(np.int64)
        self.triangles = indices.reshape(-1, 3)

    def near(self, centre: np.ndarray, radius: float) -> np.ndarray:
        corners = self.positions[self.triangles]
        middle = corners.mean(axis=1)
        keep = np.linalg.norm(middle - centre, axis=1) < radius
        return np.nonzero(keep)[0]

    def project(self, points: np.ndarray, candidates: np.ndarray
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Where each point lands on the surface, and what is there.

        Returns the point on the surface, the normal there, the texture
        coordinate there, and how far the point was from it.
        """
        best = np.full(len(points), np.inf)
        surface = np.zeros_like(points)
        hit = np.zeros(len(points), dtype=np.int64)
        for index in candidates:
            tri = self.triangles[index]
            a, b, c = self.positions[tri]
            candidate, distance = closest_on_triangle(points, a, b, c)
            closer = distance < best
            best = np.where(closer, distance, best)
            surface = np.where(closer[:, None], candidate, surface)
            hit = np.where(closer, index, hit)
        normals = np.zeros_like(points)
        uvs = np.zeros((len(points), 2))
        for row in range(len(points)):
            tri = self.triangles[hit[row]]
            corners = self.positions[tri]
            weights = barycentric(
                surface[row], corners[0], corners[1], corners[2])
            normals[row] = weights @ self.normals[tri]
            uvs[row] = weights @ self.uvs[tri]
        return surface, normals, uvs, best

    def nearest_vertices(self, points: np.ndarray,
                         candidates: np.ndarray) -> np.ndarray:
        """The body vertex each point belongs to.

        The plate is not a separate thing: it has to be carried by the
        same bones as the face it lies on, or the two drift apart when
        the head turns and the face comes through the plate.
        """
        pool = np.unique(self.triangles[candidates].reshape(-1))
        spots = self.positions[pool]
        best = np.zeros(len(points), dtype=np.int64)
        best_distance = np.full(len(points), np.inf)
        for start in range(0, len(spots), 20000):
            chunk = spots[start:start + 20000]
            distance = np.linalg.norm(
                points[:, None, :] - chunk[None, :, :], axis=2)
            nearest = distance.argmin(axis=1)
            value = distance[np.arange(len(points)), nearest]
            closer = value < best_distance
            best_distance = np.where(closer, value, best_distance)
            best = np.where(closer, pool[start + nearest], best)
        return best


# --- the plate -------------------------------------------------------------


def refine(grid: np.ndarray, rings: int, segments: int) -> np.ndarray:
    """A finer grid over the same shape.

    The plate is a grid of rings and segments; this makes more of them,
    with the new points on the straight lines between the old ones.  The
    lines are not on the face -- the face is curved, and a straight line
    between two points on it cuts through it -- so every point is put
    back onto the surface afterwards.
    """
    source_rings, source_segments = grid.shape[0], grid.shape[1]
    step = source_segments / segments
    index = np.arange(segments) * step
    low = np.floor(index).astype(int) % source_segments
    high = (low + 1) % source_segments
    frac = (index - np.floor(index))[None, :, None]
    across = grid[:, low] * (1.0 - frac) + grid[:, high] * frac
    # The rings do not wrap: the last one is the outer edge of the
    # plate, and the one after it would be back at the hole.
    step = (source_rings - 1) / (rings - 1)
    index = np.arange(rings) * step
    low = np.floor(index).astype(int)
    high = np.minimum(low + 1, source_rings - 1)
    frac = (index - np.floor(index))[:, None, None]
    return across[low] * (1.0 - frac) + across[high] * frac


def grid_indices(rings: int, segments: int) -> np.ndarray:
    """The triangles of the plate's grid.

    The plate is double-sided, and a double-sided material flips the
    normal of every back-facing fragment.  The old plate was wound so
    that its geometric front faced *into* the head and its own normals
    pointed the same way, so the flip landed them facing the camera and
    the plate was lit correctly.

    The rebuilt plate carries the face's own normals, which point out
    of the head, so the winding has to be the other way round: the
    geometric front faces the camera and the normals are used as they
    are.  Wound the old way round, the two cancel, the shading normal
    points into the head, and MToon's rim term -- which saturates the
    moment the normal turns away -- floods the whole plate with rim
    colour.  That is the pale blue oval the muzzle used to wear.
    """
    quads = []
    for ring in range(rings - 1):
        for segment in range(segments):
            a = ring * segments + segment
            b = ring * segments + (segment + 1) % segments
            c = (ring + 1) * segments + (segment + 1) % segments
            d = (ring + 1) * segments + segment
            quads.extend([a, c, b, a, d, c])
    return np.array(quads, dtype=np.int64)


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])

    asset = Asset(source)
    document = asset.document
    meshes = document["meshes"]

    body_index = next(i for i, mesh in enumerate(meshes)
                       if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(i for i, mesh in enumerate(meshes)
                        if mesh.get("name") == "YXZ_Mouth")
    cavity_index = next(i for i, mesh in enumerate(meshes)
                         if mesh.get("name") == "YXZ_MouthCavity")
    plate_material = next(i for i, material in enumerate(document["materials"])
                          if material.get("name") == "YXZ_MouthPlate")
    body_material = next(i for i, material in enumerate(document["materials"])
                          if str(material.get("name", "")).startswith("tripo_material"))

    face = Face(asset, body_index)
    mouth = meshes[mouth_index]
    primitive = mouth["primitives"][0]
    attributes = primitive["attributes"]
    base = asset.accessor(attributes["POSITION"]).astype(np.float64)
    joints = asset.accessor(attributes["JOINTS_0"])
    weights = asset.accessor(attributes["WEIGHTS_0"])
    targets = primitive.get("targets", [])

    source_rings = 6
    source_segments = 48
    if base.shape[0] != source_rings * source_segments:
        raise SystemExit("the plate is not the grid the rebuild expects")

    centre = base.mean(axis=0)
    reach = float(np.abs(base - centre).max()) + 0.06
    candidates = face.near(centre, reach)
    print("YXZ_MOUTH centre %s candidates %d"
          % (np.round(centre, 4), len(candidates)))

    surface, normals, uvs, distance = face.project(base, candidates)
    print("YXZ_MOUTH plate to face: max %.5f mean %.5f"
          % (distance.max(), distance.mean()))
    print("YXZ_MOUTH projected uvs: u %.3f..%.3f v %.3f..%.3f"
          % (uvs[:, 0].min(), uvs[:, 0].max(), uvs[:, 1].min(), uvs[:, 1].max()))
    print("YXZ_MOUTH plate bones: %s weights %s"
          % (np.unique(joints, axis=0).tolist(), np.unique(np.round(weights, 3), axis=0).tolist()))

    rings = 28
    segments = 144
    lift = 0.00040

    # The plate is projected onto the face once, and the visemes are
    # then added on top of that.
    #
    # Projecting every viseme separately looks right and is wrong.  A
    # viseme opens the mouth by pushing the inner ring away from the
    # face, and a projection puts every vertex back *on* the face, so
    # the opening is undone and the surface buckles instead -- which is
    # what turns the lip into a row of teeth when the character speaks.
    # The displacement the viseme asks for is already the right one; it
    # only has to be applied to the plate that is now on the face.
    base_grid = base.reshape(source_rings, source_segments, 3)
    fine_base = refine(base_grid, rings, segments).reshape(-1, 3)
    surface, normals, uvs, distance = face.project(fine_base, candidates)
    if distance.max() > 0.02:
        raise SystemExit("a plate point is %.4f from the face" % distance.max())
    unit = normals / np.linalg.norm(normals, axis=1, keepdims=True)

    built = [{
        "positions": surface + unit * lift,
        "surface": surface,
        "normals": unit,
        "uvs": uvs,
    }]
    for target_spec in targets:
        delta = asset.accessor(target_spec["POSITION"]).astype(np.float64)
        fine_delta = refine(
            delta.reshape(source_rings, source_segments, 3),
            rings, segments).reshape(-1, 3)
        normal_delta = asset.accessor(target_spec["NORMAL"]).astype(np.float64)
        fine_normal = refine(
            normal_delta.reshape(source_rings, source_segments, 3),
            rings, segments).reshape(-1, 3)
        moved = unit + fine_normal
        built.append({
            "positions": built[0]["positions"] + fine_delta,
            "surface": built[0]["surface"] + fine_delta,
            "normals": moved / np.linalg.norm(moved, axis=1, keepdims=True),
            "uvs": uvs,
        })
    count = built[0]["positions"].shape[0]
    print("YXZ_MOUTH new plate: %d vertices, %d triangles"
          % (count, (rings - 1) * segments * 2))

    # --- the plate --------------------------------------------------------

    new_primitive = {
        "attributes": {
            "POSITION": asset.add_accessor(built[0]["positions"], "VEC3", 34962),
            "NORMAL": asset.add_accessor(built[0]["normals"], "VEC3", 34962),
            "TEXCOORD_0": asset.add_accessor(built[0]["uvs"], "VEC2", 34962),
            "JOINTS_0": asset.add_accessor(
                face.joints[face.nearest_vertices(built[0]["positions"], candidates)],
                "VEC4", 34962),
            "WEIGHTS_0": asset.add_accessor(
                face.weights[face.nearest_vertices(built[0]["positions"], candidates)],
                "VEC4", 34962),
        },
        "indices": asset.add_accessor(grid_indices(rings, segments), "SCALAR", 34963),
        "material": primitive["material"],
    }
    new_targets = []
    for index in range(1, len(built)):
        new_targets.append({
            "POSITION": asset.add_accessor(
                built[index]["positions"] - built[0]["positions"], "VEC3"),
            "NORMAL": asset.add_accessor(
                built[index]["normals"] - built[0]["normals"], "VEC3"),
        })
    new_primitive["targets"] = new_targets
    mouth["primitives"] = [new_primitive]

    # --- the dish behind the mouth ---------------------------------------
    #
    # It has to be in front of the face, or an open mouth shows the
    # face's own white, and behind the plate, or it shows everywhere.
    # One fixed dish is enough: the plate hides all of it except the
    # part the hole uncovers, and the hole is always inside it.
    #
    # The dish is the hole in the middle of the plate, filled with
    # something dark.  It stays inside the closed lip edge, where the
    # plate hides it; the original painted smile remains visible until
    # the plate's own opening moves away from it.
    cavity = meshes[cavity_index]
    cavity_primitive = cavity["primitives"][0]
    plate_ring = built[0]["positions"].reshape(rings, segments, 3)[0]
    plate_rim = built[0]["normals"].reshape(rings, segments, 3)[0]
    middle = plate_ring.mean(axis=0)
    middle_normal = plate_rim.mean(axis=0)
    middle_normal /= np.linalg.norm(middle_normal)
    dish_rings = 4
    dish_segments = segments
    dish_positions = []
    dish_normals = []
    for ring in range(dish_rings + 1):
        radius = ring / dish_rings
        for segment in range(dish_segments):
            point = middle + (plate_ring[segment] - middle) * radius
            normal = middle_normal * (1.0 - radius) + plate_rim[segment] * radius
            normal /= np.linalg.norm(normal)
            dish_positions.append(point - normal * 0.00030)
            dish_normals.append(normal)
    dish_positions = np.asarray(dish_positions)
    dish_normals = np.asarray(dish_normals)

    dish_indices = []
    for ring in range(dish_rings):
        for segment in range(dish_segments):
            a = ring * dish_segments + segment
            b = ring * dish_segments + (segment + 1) % dish_segments
            c = (ring + 1) * dish_segments + (segment + 1) % dish_segments
            d = (ring + 1) * dish_segments + segment
            dish_indices.extend([a, c, b, a, d, c])
    dish_owner = face.nearest_vertices(dish_positions, candidates)
    dish_joints = face.joints[dish_owner]
    dish_weights = face.weights[dish_owner]

    cavity_primitive = {
        "attributes": {
            "POSITION": asset.add_accessor(dish_positions, "VEC3", 34962),
            "NORMAL": asset.add_accessor(dish_normals, "VEC3", 34962),
            "JOINTS_0": asset.add_accessor(
                dish_joints, "VEC4", 34962),
            "WEIGHTS_0": asset.add_accessor(
                dish_weights, "VEC4", 34962),
        },
        "indices": asset.add_accessor(
            np.array(dish_indices, dtype=np.int64), "SCALAR", 34963),
        "material": cavity_primitive["material"],
    }
    cavity["primitives"] = [cavity_primitive]

    # --- the plate's material --------------------------------------------
    #
    # The plate is painted with the body's own atlas, so the paint on it
    # is the paint that is already on the face.
    material = document["materials"][plate_material]
    body_texture = document["materials"][body_material][
        "pbrMetallicRoughness"]["baseColorTexture"]["index"]
    material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": body_texture}
    material["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
    material["extensions"]["VRMC_materials_mtoon"]["color"] = [1.0, 1.0, 1.0, 1.0]

    # --- the cavity's material --------------------------------------------
    #
    # The dish is a hole in the face, not a glowing thing.  The rim it
    # inherited from the body is a blue-white edge light, and on a shape
    # this size it reads as a smear of fog across the muzzle.
    cavity_material = document["materials"][cavity_primitive["material"]]
    cavity_mtoon = cavity_material.setdefault(
        "extensions", {}).setdefault("VRMC_materials_mtoon", {})
    cavity_mtoon["parametricRimColorFactor"] = [0.0, 0.0, 0.0]
    cavity_mtoon["rimLightingMixFactor"] = 0.0
    cavity_mtoon["shadingToonyFactor"] = 1.0

    asset.save(target)
    print("YXZ_MOUTH wrote %s" % target)


if __name__ == "__main__":
    main()
