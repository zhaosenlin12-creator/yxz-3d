// Turn the upstream AIRI idle into a body motion YXZ can wear.
//
// The upstream project ships one authored idle for its own character:
// `packages/stage-ui-three/src/assets/vrm/animations/idle_loop.vrma`.  It is
// a VRM Animation, and it is the reason that character reads as a person
// rather than as a prop -- one coherent movement for the whole figure,
// instead of a noise layer per bone.
//
// YXZ cannot wear it directly.  The .vrma is a hierarchy of synthetic
// nodes (torso_1..7, l_up_arm, ...) whose rest rotations are all
// identity, so the file carries *motion* and nothing else: there is no
// pose in it to copy, only the way the pose changes.  This script reads
// that motion out -- the world-space delta of every humanoid bone,
// measured against the loop's own average pose -- and writes it out as a
// small JSON asset.  The runtime turns those deltas into YXZ's own bone
// rotations against the live rig, so a rebuilt model keeps working.
//
// Usage:
//   node scripts/retarget_vrma_idle.mjs [--out <file>] [--gain <n>] [--stats]

import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { accessorReader, readGlb, readNodes } from './lib/glb.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..')
const THREE_PATH = resolve(REPO, 'node_modules/.pnpm/three@0.183.2/node_modules/three/build/three.module.js')
const THREE = await import(`file:///${THREE_PATH.replace(/\\/g, '/')}`)

const args = process.argv.slice(2)
function flag(name, fallback) {
  const at = args.indexOf(`--${name}`)
  return at < 0 ? fallback : args[at + 1]
}

const VRMA = resolve(REPO, 'packages/stage-ui-three/src/assets/vrm/animations/idle_loop.vrma')
const OUT = resolve(REPO, flag('out', 'packages/stage-ui-three/src/assets/vrm/animations/yxz-idle-authored.json'))
const GAIN = Number(flag('gain', 1))

// The humanoid bones the motion is read from.  The eyes are left out on
// purpose: YXZ's eyes are driven by the look-at controller, and a clip
// that also wrote them would fight it every frame.
const SKIP = new Set(['leftEye', 'rightEye'])

const { json, bin } = readGlb(VRMA)
const nodes = readNodes(json)
const read = accessorReader(json, bin)
const mapping = json.extensions?.VRMC_vrm_animation?.humanoid?.humanBones ?? {}
const animation = json.animations[0]

// -- the source rig ---------------------------------------------------------

const depth = nodes.map((node) => {
  let d = 0
  let p = node.parent
  while (p >= 0) {
    d++
    p = nodes[p].parent
  }
  return d
})
const order = nodes.map(node => node.index).sort((a, b) => depth[a] - depth[b])

const rotationTracks = new Map()
const times = new Set()
for (const channel of animation.channels) {
  if (channel.target.path !== 'rotation')
    continue
  const sampler = animation.samplers[channel.sampler]
  const t = Array.from(read(sampler.input))
  const v = Array.from(read(sampler.output))
  rotationTracks.set(channel.target.node, { times: t, values: v })
  for (const value of t)
    times.add(value)
}
const keyTimes = [...times].sort((a, b) => a - b)

const restLocal = nodes.map(node => new THREE.Quaternion().fromArray(node.rotation))

function sampleLocal(index, time) {
  const track = rotationTracks.get(index)
  if (!track)
    return restLocal[index].clone()
  const { times: t, values } = track
  if (time <= t[0])
    return new THREE.Quaternion().fromArray(values, 0)
  if (time >= t[t.length - 1])
    return new THREE.Quaternion().fromArray(values, (t.length - 1) * 4)
  let k = 0
  while (k < t.length - 2 && t[k + 1] < time)
    k++
  const span = t[k + 1] - t[k]
  const f = span > 0 ? (time - t[k]) / span : 0
  return new THREE.Quaternion()
    .fromArray(values, k * 4)
    .slerp(new THREE.Quaternion().fromArray(values, (k + 1) * 4), f)
}

// The world rotation of every node at one instant, walking the hierarchy
// from the root down.
function worldAt(time) {
  const world = new Array(nodes.length)
  for (const index of order) {
    const local = sampleLocal(index, time)
    const parent = nodes[index].parent
    world[index] = parent >= 0 ? world[parent].clone().multiply(local) : local.clone()
  }
  return world
}

const samples = keyTimes.map(time => worldAt(time))

// -- the reference pose -----------------------------------------------------
//
// The average of the loop, with the keys chained into one hemisphere
// first.  Quaternions are double covered, so a plain sum of a track that
// flips sign mid-loop cancels towards zero, and the average then reports
// a swing that is not there.

function meanQuaternion(list) {
  const mean = new THREE.Quaternion(0, 0, 0, 0)
  let px = 0
  let py = 0
  let pz = 0
  let pw = 1
  for (const q of list) {
    let { x, y, z, w } = q
    if (x * px + y * py + z * pz + w * pw < 0) {
      x = -x
      y = -y
      z = -z
      w = -w
    }
    px = x
    py = y
    pz = z
    pw = w
    mean.x += x
    mean.y += y
    mean.z += z
    mean.w += w
  }
  mean.normalize()
  return mean
}

const reference = new Map()
for (const [semantic, bone] of Object.entries(mapping)) {
  if (SKIP.has(semantic))
    continue
  reference.set(semantic, meanQuaternion(samples.map(world => world[bone.node])))
}

// -- the motion -------------------------------------------------------------
//
// For every bone: the world-space rotation that takes the reference pose
// to the pose at this instant.  This is the whole of the file's content
// once the pose is taken away, and it is what a different model can wear.

const bones = {}
const stats = []
for (const [semantic, bone] of Object.entries(mapping)) {
  if (SKIP.has(semantic))
    continue
  const ref = reference.get(semantic)
  const values = new Float32Array(samples.length * 4)
  let maxAngle = 0
  let path = 0
  let previous = null
  for (let i = 0; i < samples.length; i++) {
    const delta = samples[i][bone.node].clone().multiply(ref.clone().invert())
    if (GAIN !== 1) {
      // Scale the swing, not the pose: a slerp from the identity towards
      // the delta keeps the axis and shortens the arc.
      const angle = 2 * Math.acos(Math.min(1, Math.abs(delta.w)))
      if (angle > 1e-6) {
        const scale = Math.sin(angle * 0.5 * GAIN) / Math.sin(angle * 0.5)
        delta.set(delta.x * scale, delta.y * scale, delta.z * scale, delta.w * scale).normalize()
      }
    }
    values[i * 4] = delta.x
    values[i * 4 + 1] = delta.y
    values[i * 4 + 2] = delta.z
    values[i * 4 + 3] = delta.w
    const angle = 2 * Math.acos(Math.min(1, Math.abs(delta.w))) * 180 / Math.PI
    maxAngle = Math.max(maxAngle, angle)
    if (previous) {
      const step = previous.clone().invert().multiply(delta)
      path += 2 * Math.acos(Math.min(1, Math.abs(step.w))) * 180 / Math.PI
    }
    previous = delta
  }
  bones[semantic] = values
  stats.push([semantic, maxAngle, path / (keyTimes[keyTimes.length - 1] - keyTimes[0])])
}

stats.sort((a, b) => b[1] - a[1])
console.log('bone             swing(deg)  speed(deg/s)')
for (const [semantic, swing, speed] of stats)
  console.log(`${semantic.padEnd(16)} ${swing.toFixed(2).padStart(9)} ${speed.toFixed(2).padStart(11)}`)

// The loop has to close.  If the first and the last pose differ, the
// character hops once every ten seconds, which is exactly the kind of
// thing the eye finds before it finds anything else.
for (const [semantic, bone] of Object.entries(mapping)) {
  if (SKIP.has(semantic))
    continue
  const ref = reference.get(semantic)
  const first = samples[0][bone.node].clone().multiply(ref.clone().invert())
  const last = samples[samples.length - 1][bone.node].clone().multiply(ref.clone().invert())
  const gap = 2 * Math.acos(Math.min(1, Math.abs(first.dot(last)))) * 180 / Math.PI
  if (gap > 1)
    console.log(`LOOP GAP ${semantic} ${gap.toFixed(2)} deg`)
}

function pack(array) {
  return Buffer.from(array.buffer, array.byteOffset, array.byteLength).toString('base64')
}

const payload = {
  name: 'YXZ_Idle_Authored',
  source: 'packages/stage-ui-three/src/assets/vrm/animations/idle_loop.vrma',
  duration: keyTimes[keyTimes.length - 1] - keyTimes[0],
  times: pack(new Float32Array(keyTimes)),
  bones: Object.fromEntries(Object.entries(bones).map(([name, values]) => [name, pack(values)])),
}

mkdirSync(dirname(OUT), { recursive: true })
writeFileSync(OUT, `${JSON.stringify(payload)}\n`)
console.log(`\nwrote ${OUT}`)
console.log(`keys ${keyTimes.length}  duration ${payload.duration.toFixed(3)}s  bones ${Object.keys(bones).length}`)
