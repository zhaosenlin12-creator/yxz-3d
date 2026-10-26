// What the deployed VRM's animation section actually contains.
//
// Before any new motion is authored, the format has to be known exactly:
// how the samplers interpolate, what the node list looks like, and how a
// bone's animated rotation relates to its rest rotation.  Everything else
// is guesswork.
//
// Usage: node scripts/probe_yxz_glb_anim.mjs <vrm> [clipName]

import { readFileSync } from 'node:fs'

const file = process.argv[2]
const only = process.argv[3]
if (!file)
  throw new Error('usage: node scripts/probe_yxz_glb_anim.mjs <vrm> [clipName]')

const buffer = readFileSync(file)
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
  throw new Error('no JSON chunk')

const names = (json.nodes ?? []).map(node => node.name ?? '')
const components = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 }
const readers = {
  5120: [Int8Array, 1],
  5121: [Uint8Array, 1],
  5122: [Int16Array, 2],
  5123: [Uint16Array, 2],
  5125: [Uint32Array, 4],
  5126: [Float32Array, 4],
}

function read(accessorIndex) {
  const accessor = json.accessors[accessorIndex]
  const [Reader, size] = readers[accessor.componentType]
  const count = accessor.count
  const componentCount = components[accessor.type]
  const view = json.bufferViews[accessor.bufferView]
  const base = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0)
  const stride = view.byteStride ?? size * componentCount
  const out = new Reader(count * componentCount)
  const raw = bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength)
  const view2 = new DataView(raw)
  const get = (at) => {
    switch (accessor.componentType) {
      case 5120: return view2.getInt8(at)
      case 5121: return view2.getUint8(at)
      case 5122: return view2.getInt16(at, true)
      case 5123: return view2.getUint16(at, true)
      case 5125: return view2.getUint32(at, true)
      default: return view2.getFloat32(at, true)
    }
  }
  for (let i = 0; i < count; i++) {
    for (let c = 0; c < componentCount; c++)
      out[i * componentCount + c] = get(base + i * stride + c * size)
  }
  return out
}

console.log(`${file}`)
console.log(`  extensions used: ${(json.extensionsUsed ?? []).join(', ')}`)
console.log(`  nodes: ${names.length}  skins: ${(json.skins ?? []).length}`)

// The rest pose of every bone, so an authored clip can be checked against
// what the file says the bone's own rotation is.
const parentOf = new Array(names.length).fill(-1)
;(json.nodes ?? []).forEach((node, index) => {
  for (const child of node.children ?? [])
    parentOf[child] = index
})

for (const animation of json.animations ?? []) {
  if (only && animation.name !== only)
    continue
  const paths = new Map()
  let duration = 0
  for (const channel of animation.channels ?? []) {
    const sampler = animation.samplers[channel.sampler]
    const times = read(sampler.input)
    duration = Math.max(duration, times[times.length - 1] ?? 0)
    const key = `${channel.target.path}`
    paths.set(key, (paths.get(key) ?? 0) + 1)
  }
  const interps = new Set(animation.samplers.map(s => s.interpolation ?? 'LINEAR'))
  console.log(`\n=== ${animation.name}`)
  console.log(`  channels: ${animation.channels.length}  duration: ${duration.toFixed(3)}s  interpolation: ${[...interps].join(',')}`)
  console.log(`  paths: ${[...paths.entries()].map(([k, v]) => `${k}x${v}`).join(' ')}`)
  // One bone, end to end: the rest rotation, the first key, the last key,
  // and the number of keys.
  const head = animation.channels.find(c => names[c.target.node] === 'head' && c.target.path === 'rotation')
  if (head) {
    const sampler = animation.samplers[head.sampler]
    const times = read(sampler.input)
    const values = read(sampler.output)
    const node = json.nodes[head.target.node]
    console.log(`  head: ${times.length} keys, rest rot ${JSON.stringify(node.rotation ?? [0, 0, 0, 1])}`)
    const at = i => Array.from(values.slice(i * 4, i * 4 + 4)).map(v => +v.toFixed(4)).join(', ')
    console.log(`    t=${times[0].toFixed(3)} -> ${at(0)}`)
    console.log(`    t=${times[Math.floor(times.length / 2)].toFixed(3)} -> ${at(Math.floor(times.length / 2))}`)
    console.log(`    t=${times[times.length - 1].toFixed(3)} -> ${at(times.length - 1)}`)
  }
  else {
    console.log('  head: no rotation channel')
  }
}
