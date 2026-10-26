"""Minimal GLB container read/write, for patching the JSON chunk in place.

Blender's glTF exporter writes `mesh.weights` as all ones for every morph
target, which makes three-vrm start with every expression fully applied.  The
weights have to be zeroed, and the VRM 1.0 extension has to be injected into
the same JSON chunk, so both live here rather than round-tripping through a
third-party glTF writer that would drop the Draco-free skin data.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(path):
    """Return (json document, binary chunk)."""
    raw = Path(path).read_bytes()
    magic, _version, length = struct.unpack_from("<III", raw, 0)
    if magic != GLB_MAGIC:
        raise ValueError("not a glb: " + str(path))
    offset = 12
    document = None
    binary = b""
    while offset < length:
        size, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        chunk = raw[offset:offset + size]
        offset += size
        if kind == CHUNK_JSON:
            document = json.loads(chunk.decode("utf-8"))
        elif kind == CHUNK_BIN:
            binary = chunk
    if document is None:
        raise ValueError("glb has no JSON chunk: " + str(path))
    return document, binary


def write_glb(path, document, binary):
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    # The spec requires the JSON chunk first; loaders reject anything else.
    body = struct.pack("<II", len(encoded), CHUNK_JSON) + encoded
    if binary:
        padded = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
        body += struct.pack("<II", len(padded), CHUNK_BIN) + padded
    Path(path).write_bytes(struct.pack("<III", GLB_MAGIC, 2, 12 + len(body)) + body)


def neutralise_weights(document):
    """Zero every morph target weight so an import starts on the neutral pose."""
    touched = 0
    for mesh in document.get("meshes", []):
        targets = sum(len(p.get("targets", [])) for p in mesh.get("primitives", []))
        if not targets:
            continue
        mesh["weights"] = [0.0] * targets
        touched += targets
    for node in document.get("nodes", []):
        if "weights" in node:
            node["weights"] = [0.0] * len(node["weights"])
    return touched


def prune_buffers(document, binary):
    """Drop buffer views nothing points at any more, and repack the BIN chunk.

    Converting the material to MToon throws away the normal map and the
    metallic-roughness map, which on this asset are together larger than the
    base colour atlas.  Leaving them in would ship six megabytes of pixels
    that no shader ever samples.

    Reachability is found by walking the whole document for `bufferView`
    keys rather than by enumerating the known glTF pointer sites.  That list
    is easy to get wrong: `skin.inverseBindMatrices` is an *accessor* index,
    not a buffer view index, so treating it as one both pins an unrelated
    buffer alive and corrupts the skin with a buffer-view remap.
    """
    prune_textures(document)
    views = document.get("bufferViews", [])
    used = set(collect_buffer_view_refs(document))
    if not views:
        return binary, 0

    kept = sorted(index for index in range(len(views))
                  if index in used and index < len(views))
    if len(kept) == len(views):
        return binary, 0

    # Anything that pointed at a dropped view (a whole accessor or image) has
    # to fail loudly here rather than leave a dangling index behind.
    stale = used - set(kept)
    if stale:
        raise ValueError(
            "buffer view(s) %s are referenced but absent" % sorted(stale))

    remap = {old: new for new, old in enumerate(kept)}
    chunks = []
    new_views = []
    offset = 0
    for old in kept:
        view = dict(views[old])
        start = view.get("byteOffset", 0)
        chunks.append(binary[start:start + view["byteLength"]])
        view["byteOffset"] = offset
        offset += view["byteLength"]
        # Keep the 4-byte alignment the accessors expect.
        padding = (4 - offset % 4) % 4
        if padding:
            chunks.append(b"\x00" * padding)
            offset += padding
        new_views.append(view)
    # The padding has to be part of the packed data, not just of the offsets.
    # Omitting it lets every view after the first unaligned one drift, and
    # leaves the last view pointing past the end of the BIN chunk.
    packed = b"".join(chunks)
    document["bufferViews"] = new_views

    remap_buffer_views(document, remap)

    document["buffers"] = [{"byteLength": len(packed)}]
    return packed, len(views) - len(kept)


def collect_buffer_view_refs(node, found=None):
    """Every `bufferView` index reachable from `node`, sparse accessors included."""
    if found is None:
        found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "bufferView" and isinstance(value, int):
                found.add(value)
            else:
                collect_buffer_view_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_buffer_view_refs(value, found)
    return found


def remap_buffer_views(node, remap):
    """Rewrite every live `bufferView` index through `remap`, in place."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "bufferView" and isinstance(value, int):
                node[key] = remap[value]
            else:
                remap_buffer_views(value, remap)
    elif isinstance(node, list):
        for value in node:
            remap_buffer_views(value, remap)


# Every slot a glTF material can point a texture at, including the MToon
# extension's own slots.
TEXTURE_SLOTS = (
    "baseColorTexture",
    "metallicRoughnessTexture",
    "normalTexture",
    "occlusionTexture",
    "emissiveTexture",
)

MTOON_TEXTURE_SLOTS = (
    "texture",
    "shadeTexture",
    "shadeShiftTexture",
    "reflectanceTexture",
    "reflectanceShiftTexture",
    "rimTexture",
    "emissiveTexture",
    "emissiveMultiplyTexture",
    "outlineWidthMultiplyTexture",
)


def prune_textures(document):
    """Remove textures and images no material refers to, and renumber them."""
    materials = document.get("materials", [])
    textures = document.get("textures", [])
    images = document.get("images", [])
    if not textures:
        return 0

    used_textures = set()
    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {})
        for slot in TEXTURE_SLOTS:
            index = pbr.get(slot, {}).get("index")
            if index is not None:
                used_textures.add(index)
            index = material.get(slot, {}).get("index")
            if index is not None:
                used_textures.add(index)
        mtoon = material.get("extensions", {}).get("VRMC_materials_mtoon", {})
        for slot in MTOON_TEXTURE_SLOTS:
            index = mtoon.get(slot)
            if isinstance(index, int):
                used_textures.add(index)

    kept_textures = sorted(index for index in range(len(textures))
                           if index in used_textures)
    if len(kept_textures) == len(textures):
        return 0

    texture_remap = {old: new for new, old in enumerate(kept_textures)}
    used_images = set()
    new_textures = []
    for old in kept_textures:
        texture = dict(textures[old])
        source = texture.get("source")
        if source is not None:
            used_images.add(source)
        new_textures.append(texture)
    document["textures"] = new_textures

    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {})
        for slot in TEXTURE_SLOTS:
            index = pbr.get(slot, {}).get("index")
            if index is not None:
                pbr[slot]["index"] = texture_remap[index]
        for slot in TEXTURE_SLOTS:
            index = material.get(slot, {}).get("index")
            if index is not None:
                material[slot]["index"] = texture_remap[index]
        mtoon = material.get("extensions", {}).get("VRMC_materials_mtoon", {})
        for slot in MTOON_TEXTURE_SLOTS:
            index = mtoon.get(slot)
            if isinstance(index, int):
                mtoon[slot] = texture_remap[index]

    kept_images = sorted(index for index in range(len(images))
                         if index in used_images)
    if len(kept_images) != len(images):
        image_remap = {old: new for new, old in enumerate(kept_images)}
        document["images"] = [images[index] for index in kept_images]
        for texture in document["textures"]:
            source = texture.get("source")
            if source is not None:
                texture["source"] = image_remap[source]
    return len(textures) - len(kept_textures)
