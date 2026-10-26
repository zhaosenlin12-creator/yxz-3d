// Minimal glTF-binary reader.
//
// The motion work needs to look at the node hierarchy and the animation
// samplers of a .vrm / .vrma / .glb file without going through a GPU or a
// DOM, so this reads the container directly.  Only the parts the motion
// pipeline needs are implemented: the JSON chunk, the binary chunk, and
// the accessor readers.

import { readFileSync } from 'node:fs'

const COMPONENT_READERS = {
  5120: Int8Array,
  5121: Uint8Array,
  5122: Int16Array,
  5123: Uint16Array,
  5125: Uint32Array,
  5126: Float32Array,
}

const COMPONENT_COUNT = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT2: 4, MAT3: 9, MAT4: 16 }

export function readGlb(file) {
  const buffer = readFileSync(file)
  if (buffer.readUInt32LE(0) !== 0x46546C67)
    throw new Error(`${file} is not a GLB`)
  let offset = 12
  let json = null
  let bin = null
  while (offset + 8 <= buffer.length) {
    const length = buffer.readUInt32LE(offset)
    const type = buffer.readUInt32LE(offset + 4)
    const start = offset + 8
    if (type === 0x4E4F534A)
      json = JSON.parse(buffer.toString('utf8', start, start + length))
    else if (type === 0x004E4942)
      bin = buffer.subarray(start, start + length)
    offset = start + length + ((4 - (length % 4)) % 4)
  }
  if (!json)
    throw new Error(`${file} has no JSON chunk`)
  return { json, bin }
}

function binLike(bin) {
  if (!bin.__view)
    bin.__view = new DataView(bin.buffer, bin.byteOffset, bin.byteLength)
  return bin.__view
}

function readRaw(bin, byteOffset, componentType) {
  const view = binLike(bin)
  switch (componentType) {
    case 5120: return view.getInt8(byteOffset)
    case 5121: return view.getUint8(byteOffset)
    case 5122: return view.getInt16(byteOffset, true)
    case 5123: return view.getUint16(byteOffset, true)
    case 5125: return view.getUint32(byteOffset, true)
    default: return view.getFloat32(byteOffset, true)
  }
}

export function accessorReader(gltf, bin) {
  return function read(index) {
    const accessor = gltf.accessors[index]
    const components = COMPONENT_COUNT[accessor.type]
    if (!COMPONENT_READERS[accessor.componentType] || !components)
      throw new Error(`unsupported accessor ${accessor.type}/${accessor.componentType}`)
    const bytes = COMPONENT_READERS[accessor.componentType].BYTES_PER_ELEMENT
    const size = bytes * components
    const view = gltf.bufferViews[accessor.bufferView]
    const base = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0)
    const stride = view.byteStride ?? size
    const count = accessor.count
    const out = new COMPONENT_READERS[accessor.componentType](count * components)
    if (stride === size) {
      for (let i = 0; i < out.length; i++)
        out[i] = readRaw(bin, base + i * bytes, accessor.componentType)
      return out
    }
    for (let i = 0; i < count; i++)
      for (let c = 0; c < components; c++)
        out[i * components + c] = readRaw(bin, base + i * stride + c * bytes, accessor.componentType)
    return out
  }
}

// The node hierarchy as plain records: a name, a parent, and the local
// transform.  Nothing here needs a scene graph, and the motion pipeline
// only ever reads it.
export function readNodes(gltf) {
  const nodes = (gltf.nodes ?? []).map((source, index) => ({
    index,
    name: source.name ?? `node-${index}`,
    parent: -1,
    children: source.children ?? [],
    translation: source.translation ?? [0, 0, 0],
    rotation: source.rotation ?? [0, 0, 0, 1],
    scale: source.scale ?? [1, 1, 1],
  }))
  for (const node of nodes) {
    for (const child of node.children)
      nodes[child].parent = node.index
  }
  return nodes
}
