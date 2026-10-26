// Offline motion probe.
//
// The headless browser in this box renders the YXZ stage at about 0.6fps, so
// iterating on idle motion by screenshotting it is not possible.  This runs
// the same AnimationMixer over the same VRM offline at 60Hz and reports the
// numbers that actually decide whether a motion reads as alive or as a tic:
//
//   spread   how far the bone ever gets from the pose it holds on average
//   wander   how far it gets from where the clip alone would have put it
//   speed    degrees of arc per minute, i.e. how much motion is on screen
//   cycle    how well the pose at t matches the pose at t+6s.  A loop sits
//            near 1.  A figure that is actually alive sits low, because no
//            part of it repeats on a schedule the eye can learn.
//
// What it measures: the *behaviour layer* -- the head's aim, the small
// movements, the wings and the ring -- and the state clips underneath
// them.  The body itself is not in here any more: it is driven by the
// upstream AIRI idle, retargeted onto this rig, which lives in
// `composables/vrm/authored-idle.ts` and is measured, as a whole figure,
// by `scripts/capture_yxz_film.mjs` and `scripts/analyze_yxz_film.mjs`.
// A number from this probe about the hips or the spine is about the
// behaviour layer's share of those bones, which is nothing.
//
// Usage:
//   node scripts/probe_yxz_motion.mjs --vrm <file> [--clip <name>]
//   node scripts/probe_yxz_motion.mjs --vrm <file> --life <scene.vue>
//   node scripts/probe_yxz_motion.mjs --vrm <file> --calm <scene.vue>

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'

const REPO = resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const THREE_CANDIDATES = [
  'node_modules/three/build/three.module.js',
  'node_modules/.pnpm/three@0.183.2/node_modules/three/build/three.module.js',
]
const THREE_PATH = THREE_CANDIDATES
  .map(path => resolve(REPO, path))
  .find(existsSync)
if (!THREE_PATH)
  throw new Error(`three not found; looked in ${THREE_CANDIDATES.join(', ')}`)
const THREE = await import(`file:///${THREE_PATH.replace(/\\/g, '/')}`)

const COMPONENT_READERS = {
  5120: Int8Array,
  5121: Uint8Array,
  5122: Int16Array,
  5123: Uint16Array,
  5125: Uint32Array,
  5126: Float32Array,
}
const COMPONENT_COUNT = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 }

function readGlb(file) {
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

function accessorReader(gltf, bin) {
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

// Rebuilds the node hierarchy from the glTF document, with no meshes: the
// measurement only cares about rotations, and leaving the skinned meshes out
// keeps this to a few hundred milliseconds of Node instead of a GPU.
function buildRig(gltf) {
  const nodes = []
  for (const source of gltf.nodes ?? []) {
    const node = new THREE.Bone()
    if (source.name)
      node.name = source.name
    if (source.translation)
      node.position.fromArray(source.translation)
    if (source.rotation)
      node.quaternion.fromArray(source.rotation)
    if (source.scale)
      node.scale.fromArray(source.scale)
    nodes.push(node)
  }
  // Parent links first, roots second.  Doing it in one pass over the nodes
  // re-parents every leaf out of its own parent, because a leaf is reached
  // after its parent has already claimed it.
  for (let i = 0; i < nodes.length; i++) {
    for (const child of gltf.nodes[i].children ?? [])
      nodes[i].add(nodes[child])
  }
  const root = new THREE.Object3D()
  root.name = 'gltf-root'
  for (const node of nodes)
    if (!node.parent)
      root.add(node)
  root.updateMatrixWorld(true)
  const byName = new Map()
  root.traverse(node => node.name && byName.set(node.name, node))
  return { root, byName }
}

function buildClips(gltf, read) {
  const clips = []
  for (const source of gltf.animations ?? []) {
    const tracks = []
    for (const channel of source.channels) {
      const node = gltf.nodes[channel.target.node]
      if (!node?.name)
        continue
      const sampler = source.samplers[channel.sampler]
      if (sampler.interpolation && sampler.interpolation !== 'LINEAR' && sampler.interpolation !== 'STEP')
        continue
      const times = Array.from(read(sampler.input))
      const values = read(sampler.output)
      const size = channel.target.path === 'rotation' ? 4 : 3
      const flat = Array.from(values)
      // STEP holds each key until the next one.  Emulating that with a
      // duplicated key a hair before the next time turns it into the linear
      // case, which the mixer already knows how to do.  Dropping these
      // channels instead would leave the bone unwritten, and the living layer
      // would then accumulate on top of itself every frame.
      const stepped = sampler.interpolation === 'STEP'
      const held = stepped ? holdKeys(times, flat, size) : { times, values: flat }
      if (channel.target.path === 'rotation') {
        tracks.push(new THREE.QuaternionKeyframeTrack(
          `${node.name}.quaternion`,
          Float32Array.from(held.times),
          Float32Array.from(held.values),
        ))
      }
      else if (channel.target.path === 'translation') {
        const kept = []
        for (let i = 0; i < held.values.length; i += size)
          kept.push(held.values[i], held.values[i + 1], held.values[i + 2])
        tracks.push(new THREE.VectorKeyframeTrack(
          `${node.name}.position`,
          Float32Array.from(held.times),
          Float32Array.from(kept),
        ))
      }
    }
    if (tracks.length > 0) {
      // three's constructor is (name, duration, tracks) -- passing two
      // arguments puts the track array where the duration belongs and
      // silently produces a clip with no tracks at all.
      clips.push(new THREE.AnimationClip(source.name ?? `clip-${clips.length}`, -1, tracks))
    }
  }
  return clips
}

// Doubles every key, holding each value until just before the next one.
function holdKeys(times, source, size) {
  const outTimes = []
  const outValues = []
  for (let index = 0; index < times.length; index++) {
    const next = times[index + 1]
    outTimes.push(times[index], next === undefined ? times[index] + 1 / 30 : times[index] + (next - times[index]) * 0.999)
    for (let repeat = 0; repeat < 2; repeat++)
      for (let c = 0; c < size; c++)
        outValues.push(source[index * size + c])
  }
  return { times: outTimes, values: outValues }
}

function chainWorldQuaternion(node, out) {
  out.copy(node.quaternion)
  let parent = node.parent
  while (parent) {
    out.premultiply(parent.quaternion)
    parent = parent.parent
  }
  return out
}

const DEG = 180 / Math.PI

// The four numbers that describe a bone's motion over a run.
function describe(samples) {
  const n = samples.length
  if (n < 3)
    return null
  const mean = new THREE.Quaternion(0, 0, 0, 0)
  // Chained into one hemisphere before summing.  An exporter is free to write
  // q or -q for the same rotation and this model's clips do flip sign
  // mid-track; summed raw, those keys cancel and the mean collapses towards
  // zero, which then reports every bone as swinging through 180 degrees.
  let previousX = 0
  let previousY = 0
  let previousZ = 0
  let previousW = 1
  for (const q of samples) {
    let { x, y, z, w } = q
    if (x * previousX + y * previousY + z * previousZ + w * previousW < 0) {
      x = -x
      y = -y
      z = -z
      w = -w
    }
    previousX = x
    previousY = y
    previousZ = z
    previousW = w
    mean.x += x
    mean.y += y
    mean.z += z
    mean.w += w
  }
  mean.normalize()
  // How far each sample sits from the mean pose, as a rotation vector in the
  // mean's own frame.  When a bone circles its head, those three components
  // run in quadrature and their correlations go to one; when it breathes or
  // shifts its weight they are close to independent.  This is the number
  // that separates "alive" from "spinning".
  const inverse = mean.clone().invert()
  const deviation = new THREE.Quaternion()
  const series = samples.map((q) => {
    deviation.copy(inverse).multiply(q)
    const w = Math.min(1, Math.abs(deviation.w))
    const angle = 2 * Math.acos(w)
    const scale = angle < 1e-6 ? 2 : angle / Math.sqrt(Math.max(1e-12, 1 - w * w))
    return [deviation.x * scale, deviation.y * scale, deviation.z * scale]
  })
  let spread = 0
  let spreadAt = 0
  let speed = 0
  const lagFrames = Math.round(6 * 60)
  let lagSq = 0
  let lagTotal = 0
  const sums = [0, 0, 0]
  const squares = [0, 0, 0]
  const crosses = [0, 0, 0]
  // How much of the run the bone spends sitting still.
  //
  // This is the number that decides whether a figure reads as calm or as
  // restless, and it is the one the eye is actually judging.  A bone that
  // is always within a degree of where it usually sits looks like it is
  // standing; a bone that is always three degrees away from it looks like
  // it is fidgeting, however smooth and however non-repeating the path is.
  let quiet = 0
  // How much of the run the bone is not moving at all.
  //
  // `quiet` above measures distance from the average pose, which is the
  // wrong question for a figure that holds several different poses for long
  // stretches: it is holding still, just not near the mean.  This one asks
  // the question the eye actually asks -- has this thing changed in front of
  // me -- and it asks it over a half-second window, because that is roughly
  // how long the eye holds an image before deciding it has moved.
  //
  // A velocity threshold was tried first and is the wrong instrument: the
  // anti-freeze tremor is two degrees per second at an amplitude of three
  // hundredths of a degree, which is invisible but scores as busy.  Change
  // over time, not speed, is what the eye reads.
  let held = 0
  let moving = 0
  let episodes = 0
  let inMove = false
  let runLength = 0
  const halfSecond = Math.round(0.5 * 60)
  const reaches = []
  for (let i = 0; i < n; i++) {
    const parts = series[i]
    for (let a = 0; a < 3; a++) {
      sums[a] += parts[a]
      squares[a] += parts[a] * parts[a]
    }
    crosses[0] += parts[0] * parts[1]
    crosses[1] += parts[0] * parts[2]
    crosses[2] += parts[1] * parts[2]
    const reach = 2 * Math.acos(Math.min(1, Math.abs(samples[i].dot(mean)))) * DEG
    reaches.push(reach)
    if (reach < 1)
      quiet++
    if (reach > spread) {
      spread = reach
      spreadAt = i
    }
    if (i > 0) {
      speed += 2 * Math.acos(Math.min(1, Math.abs(samples[i].dot(samples[i - 1])))) * DEG
    }
    if (i > halfSecond) {
      const moved = 2 * Math.acos(Math.min(1, Math.abs(samples[i].dot(samples[i - halfSecond])))) * DEG
      if (moved < 0.4)
        held++
      if (moved > 0.4) {
        moving++
        runLength++
      }
      else if (runLength > 0) {
        // An episode only counts once the motion has lasted long enough to
        // be something a person did rather than a frame of sampling noise.
        if (runLength > 6)
          episodes++
        runLength = 0
      }
    }
    if (i + lagFrames < n) {
      const lag = 2 * Math.acos(Math.min(1, Math.abs(samples[i].dot(samples[i + lagFrames])))) * DEG
      lagSq += lag * lag
      lagTotal++
    }
  }
  return {
    spread: +spread.toFixed(2),
    spreadAt: +(spreadAt / 60).toFixed(1),
    speed: +(speed / (n / 60) / 10).toFixed(1),
    lag: +(lagTotal ? Math.sqrt(lagSq / lagTotal) : 0).toFixed(2),
    quiet: Math.round((quiet / n) * 100),
    held: Math.round((held / Math.max(1, n - 1)) * 100),
    episodes,
    moving: Math.round((moving / Math.max(1, n - 1)) * 100),
    percentiles: [0.1, 0.5, 0.9].map(q =>
      +reaches.slice().sort((a, b) => a - b)[Math.min(n - 1, Math.floor(q * n))].toFixed(1)),
    axes: axisStats(sums, squares, crosses, n),
  }
}

// Per-axis spread in degrees, and the three correlations between the axes.
function axisStats(sums, squares, crosses, n) {
  const means = sums.map(sum => sum / n)
  const sigma = squares.map((square, axis) => Math.sqrt(Math.max(0, square / n - means[axis] ** 2)))
  const correlate = (a, b, cross) => (sigma[a] * sigma[b] > 1e-9
    ? (cross / n - means[a] * means[b]) / (sigma[a] * sigma[b])
    : 0)
  return {
    x: +(sigma[0] * DEG).toFixed(2),
    y: +(sigma[1] * DEG).toFixed(2),
    z: +(sigma[2] * DEG).toFixed(2),
    cxy: +correlate(0, 1, crosses[0]).toFixed(2),
    cxz: +correlate(0, 2, crosses[1]).toFixed(2),
    cyz: +correlate(1, 2, crosses[2]).toFixed(2),
  }
}

// ---------------------------------------------------------------------------
// The living layer, lifted out of the component.
//
// A copy of these numbers would be a lie within one edit: the whole point of
// measuring is to tune the values that are actually on screen.  So the
// constants are parsed out of the component source and the two signal
// functions are evaluated from their own text, which means the probe cannot
// drift away from what the browser runs.

function extractFunction(source, name) {
  const head = source.indexOf(`function ${name}(`)
  if (head < 0)
    throw new Error(`${name} not found`)
  const body = source.indexOf('{', head)
  let depth = 0
  for (let i = body; i < source.length; i++) {
    if (source[i] === '{')
      depth++
    else if (source[i] === '}' && --depth === 0)
      return stripTypes(source.slice(head, i + 1))
  }
  throw new Error(`${name} is not closed`)
}

// The component is written in TypeScript; the signals it lifts are plain
// arithmetic once the annotations are off.
function stripTypes(text) {
  return text
    // Interfaces and type aliases have no runtime meaning at all, and
    // they are the only TypeScript in the motion core that cannot be
    // stripped by a rule: their bodies are declarations, not values.
    .replace(/^interface\s+\w+(?:<[^>]*>)?\s*\{[\s\S]*?^\}\s*$/gm, '')
    .replace(/^type\s+\w+(?:<[^>]*>)?\s*=[^\n]*$/gm, '')
    .replace(/\s*:\s*number\b/g, '')
    // Local declarations: `const segment: PostureSegment = {`.
    .replace(/^(\s*(?:const|let)\s+\w+)\s*:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)(\s*=)/gm, '$1$3')
    // Parameter annotations: `(k, action: LifeAction)` and
    // `(status: YXZStatus)`.  Only inside the signature, which is the text
    // before the first `{`.
    .replace(/^(\s*(?:export\s+)?function\s+\w+\s*\(([^)]*)\))/gm,
      (_, signature, params) => `${signature.replace(/:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)/g, '')}`)
    // Arrow functions carry their annotations in the parameter list, and
    // the parameter list is not a function signature, so it needs its
    // own rule.
    .replace(/(\([^()]*\))(\s*=>)/g,
      (_, params, arrow) => params.replace(/:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)/g, '') + arrow)
}

// The motion core, lifted whole.
//
// The component keeps the whole of its idle motion in one marked
// block, and the probe takes that block as it is.  Lifting the block
// rather than the pieces is the only way the measurement can be the
// same body as the one on screen: the pieces are written to be read
// together, and a probe that reads them apart is measuring something
// that does not exist.
function extractMotionCore(source) {
  const begin = source.indexOf('>>> YXZ MOTION CORE BEGIN')
  const end = source.indexOf('<<< YXZ MOTION CORE END')
  if (begin < 0 || end < 0)
    throw new Error('the motion core block is missing')
  return source.slice(source.indexOf('\n', begin) + 1, end)
}

function extractCallTable(source, name) {
  const head = source.indexOf(`const ${name}`)
  if (head < 0)
    throw new Error(`${name} not found`)
  const open = source.indexOf('[', source.indexOf('=', head))
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '[')
      depth++
    else if (source[i] === ']' && --depth === 0) {
      const literal = source.slice(open, i + 1)
      return literal.replace(/\/\/[^\n]*/g, '').replace(/\s+/g, ' ')
    }
  }
  throw new Error(`${name} is not closed`)
}

function loadLifeLayer(vuePath) {
  const source = readFileSync(vuePath, 'utf8')
  // lifeDrift closes over the drift tables, so they travel with it.
  const tables = ['DRIFT_AXIS', 'DRIFT_TERM', 'DRIFT_WEIGHT', 'DRIFT_PHASE']
    .map(name => `${name} = ${extractArrayConst(source, name)};`)
    .join('\n')
  const lifeDrift = new Function(`${tables}\nreturn ${extractFunction(source, 'lifeDrift')}`)()
  const lifeMicro = new Function('return ' + extractFunction(source, 'lifeMicro'))()
  const smoothstepRaw = new Function('THREE', 'return ' + extractFunction(source, 'smoothstep'))(THREE)
  const smoothstep = smoothstepRaw
  const lifeBreath = new Function(`const BREATH_BASE = ${/const BREATH_BASE = ([\d.]+)/.exec(source)?.[1] ?? 4.35}\nreturn ${extractFunction(source, 'lifeBreath')}`)()
  const bones = new Function(`return ${extractCallTable(source, 'LIFE_BONES')}`)()
  const actions = new Function(`return ${extractLiteral(source, 'LIFE_ACTIONS')}`)()
  const actionBias = new Function(`return ${extractLiteral(source, 'LIFE_ACTION_BIAS')}`)()
  const stateWeight = new Function(`return ${extractLiteral(source, 'LIFE_STATE_WEIGHT')}`)()
  const attentionShape = new Function(`return ${extractLiteral(source, 'ATTENTION_SHAPE')}`)()
  const attentionGain = new Function(`return ${extractLiteral(source, 'ATTENTION_GAIN')}`)()
  const attentionCeiling = new Function(`return ${extractLiteral(source, 'ATTENTION_CEILING')}`)()
  // The ratio between the chin and the tilt.  It is read here rather
  // than out of the motion core because the attention model needs it
  // too: the tilt follows the chin, and the attention model has to
  // keep the two together or the head draws an ellipse.
  const headRockRatio = Number(constValue(source, 'HEAD_ROCK_RATIO'))
  // The two signal functions and the picker are evaluated from their own
  // text so the probe cannot drift away from what the browser runs.
  const actionEnvelope = new Function('THREE', 'smoothstep',
    `return ${extractFunction(source, 'actionEnvelope')}`)(THREE, smoothstep)
  // `nextLifeGap` keeps a burst counter in the component's module scope, so
  // the probe mirrors it through an object it syncs back on every call.
  const gapState = { lifeBurstLeft: 0 }
  const nextLifeGap = new Function('gapState', `
    let lifeBurstLeft = gapState.lifeBurstLeft
    const fn = ${extractFunction(source, 'nextLifeGap')}
    return (...args) => {
      const value = fn(...args)
      gapState.lifeBurstLeft = lifeBurstLeft
      return value
    }
  `)(gapState)
  const attentionEnvelope = new Function('smoothstep',
    `return ${extractFunction(source, 'attentionEnvelope')}`)(smoothstep)

  // The noise the idle is built from, lifted with everything else so the
  // probe cannot drift away from what the browser runs.  The seed is fixed
  // here so two runs of the probe are comparable.
  const motionSeed = 12345
  const noiseBlock = ['motionHash', 'motionNoise', 'motionFbm']
    .map(name => extractFunction(source, name))
    .join('\n')
  const motionFbm = new Function('MOTION_SEED', `${noiseBlock}\nreturn motionFbm`)(motionSeed)
  // The settle a held look drifts through, so a long hold is alive
  // without being a movement.
  const attentionDrift = new Function('THREE', 'MOTION_SEED',
    `${noiseBlock}\nconst ATTENTION_DRIFT = ${/const ATTENTION_DRIFT = ([\d.]+)/.exec(source)?.[1] ?? 0.42};\nreturn ${extractFunction(source, 'attentionDrift')}`)(
      THREE, motionSeed)

  // The attention state machine, lifted the same way.  It is a module-level
  // singleton in the component, so the probe keeps one here too and resets
  // it between runs exactly where the component resets it on teardown.
  const attention = { yaw: 0, pitch: 0, roll: 0 }
  const attentionFrom = { yaw: 0, pitch: 0, roll: 0 }
  const attentionTo = { yaw: 0, pitch: 0, roll: 0 }
  const attentionNow = { yaw: 0, pitch: 0, roll: 0 }
  const attentionState = { start: -1, dur: 1, nextAt: 3.6, side: 1 }
  const clampAttention = new Function('THREE', 'ATTENTION_CEILING',
    `return ${extractFunction(source, 'clampAttention')}`)(THREE, attentionCeiling)
  const pickAttention = new Function(
    'THREE', 'ATTENTION_SHAPE', 'ATTENTION_CEILING', 'clampAttention',
    'attention', 'attentionFrom', 'attentionTo', 'attentionNow', 'attentionState',
    'HEAD_ROCK_RATIO',
    `
      let attentionSide = attentionState.side
      let attentionDur = attentionState.dur
      const fn = ${extractFunction(source, 'pickAttention')}
      return (status) => {
        const value = fn(status)
        attentionState.side = attentionSide
        attentionState.dur = attentionDur
        return value
      }
    `,
  )(THREE, attentionShape, attentionCeiling, clampAttention, attention, attentionFrom, attentionTo, attentionNow, attentionState,
    headRockRatio)
  const updateAttention = new Function(
    'THREE', 'ATTENTION_SHAPE', 'attentionEnvelope', 'smoothstep', 'pickAttention', 'attentionDrift',
    'attention', 'attentionFrom', 'attentionTo', 'attentionNow', 'attentionState',
    `
      let attentionStart = attentionState.start
      let attentionDur = attentionState.dur
      let attentionNextAt = attentionState.nextAt
      const attentionDriftSample = new THREE.Vector3()
      const fn = ${extractFunction(source, 'updateAttention')}
      return (time, status) => {
        const value = fn(time, status)
        attentionState.start = attentionStart
        attentionState.dur = attentionDur
        attentionState.nextAt = attentionNextAt
        return value
      }
    `,
  )(THREE, attentionShape, attentionEnvelope, smoothstep, pickAttention, attentionDrift, attention, attentionFrom, attentionTo, attentionNow, attentionState)

  // The shared sway and its lag.  Same treatment: the component gives
  // every bone one signal read a beat late, and the probe has to
  // reproduce that or it is measuring a different body.
  const swayScalars = [
    'SWAY_CELL',
    'SWAY_FLOOR',
    'POSTURE_GAIN',
    'SWAY_PHASE_PITCH',
    'SWAY_PHASE_YAW',
    'SWAY_PHASE_ROLL',
  ]
    .map(name => {
      const value = constValue(source, name)
      if (value === undefined)
        throw new Error(`${name} not found`)
      return `const ${name} = ${value};`
    })
    .join('\n')
  const swayValue = new Function('MOTION_SEED',
    `${noiseBlock}\n${swayScalars}\nreturn ${extractFunction(source, 'swayValue')}`)(motionSeed)
  const swaySwell = new Function('MOTION_SEED', 'smoothstep',
    `${noiseBlock}\n${swayScalars}\nreturn ${extractFunction(source, 'swaySwell')}`)(motionSeed, smoothstep)
  // The motion core, lifted whole.
  //
  // The walks, the small movements and the shape of the head are all
  // in one block in the component, and they are state machines over
  // module-level singletons there.  The probe takes the block as it
  // is and resets it between runs, exactly as the component resets it
  // on teardown.
  const motion = new Function(
    'THREE', 'smoothstep', 'ATTENTION_SHAPE', 'ATTENTION_GAIN', 'HEAD_ROCK_RATIO',
    'attentionNow', 'motionFbm', 'MOTION_SEED',
    `${stripTypes(extractMotionCore(source))}
return {
  updateMotionLevels,
  updateHeadShape,
  lifeWeight,
  resetMotion,
  get chainLean() { return motionChainLean },
  get rootLean() { return motionRootLean },
  get headSway() { return swayHead },
  get gestureCount() { return headGestureCount },
  HEAD_ROCK_RATIO,
}`,
  )(THREE, smoothstep, attentionShape, attentionGain, headRockRatio, attentionNow, motionFbm, motionSeed)
  const updateHeadShape = motion.updateHeadShape
  const lifeWeight = motion.lifeWeight
  // The weight shift, and the bones that take it.  The signal is one
  // number for the whole figure, so the probe has to have it or it is
  // measuring a body that never shifts its weight.
  const weightSway = new Function(`return ${extractLiteral(source, 'WEIGHT_SWAY')}`)()
  const samplePosture = new Function('THREE', 'swayValue', 'swaySwell',
    'SWAY_CELL', 'POSTURE_GAIN',
    'SWAY_PHASE_PITCH', 'SWAY_PHASE_YAW', 'SWAY_PHASE_ROLL',
    `return ${extractFunction(source, 'samplePosture')}`)(
      THREE,
      swayValue,
      swaySwell,
      Number(/const SWAY_CELL = ([\d.]+)/.exec(source)?.[1] ?? 11.3),
      Number(/const POSTURE_GAIN = ([\d.]+)/.exec(source)?.[1] ?? 0.72),
      Number(/const SWAY_PHASE_PITCH = ([\d.]+)/.exec(source)?.[1] ?? 0),
      Number(/const SWAY_PHASE_YAW = ([\d.]+)/.exec(source)?.[1] ?? 17.3),
      Number(/const SWAY_PHASE_ROLL = ([\d.]+)/.exec(source)?.[1] ?? 33.7),
    )

  const history = []
  const pickLifeAction = new Function('LIFE_ACTIONS', 'LIFE_ACTION_BIAS', 'lifeHistory',
    `return ${extractFunction(source, 'pickLifeAction')}`)(actions, actionBias, history)
  return {
    lifeDrift,
    lifeMicro,
    bones,
    actions,
    torsoFollow: Number(/const TORSO_FOLLOW = ([\d.]+)/.exec(source)?.[1] ?? 0.35),
    actionBias,
    stateWeight,
    actionEnvelope,
    nextLifeGap,
    pickLifeAction,
    attentionEnvelope,
    attentionShape,
    attentionGain,
    attention,
    attentionNow,
    attentionState,
    pickAttention,
    updateAttention,
    samplePosture,
    swayValue,
    swaySwell,
    updateHeadShape,
    updateMotionLevels: motion.updateMotionLevels,
    motionChainLean: () => motion.chainLean,
    motionRootLean: () => motion.rootLean,
    headSway: () => motion.headSway,
    gestureCount: () => motion.gestureCount,
    headRockRatio: motion.HEAD_ROCK_RATIO,
    lifeWeight,
    weightSway,
    lifeBreath,
    gapState,
    resetAttention() {
      Object.assign(attention, { yaw: 0, pitch: 0, roll: 0 })
      Object.assign(attentionFrom, { yaw: 0, pitch: 0, roll: 0 })
      Object.assign(attentionTo, { yaw: 0, pitch: 0, roll: 0 })
      Object.assign(attentionNow, { yaw: 0, pitch: 0, roll: 0 })
      Object.assign(attentionState, { start: -1, dur: 1, nextAt: 3.6, side: 1 })
      // The walks and the small movements are state machines too, and
      // a run that starts half way through a walk is a different
      // measurement from one that starts at the beginning of one.
      motion.resetMotion()
    },
    history,
    boneIndex: new Map(bones.map((item, index) => [item.bone, index])),
  }
}

// Reads a `const NAME = [ ... ]` or `= { ... }` literal out of the
// component, comments and all.
function extractLiteral(source, name) {
  const head = source.indexOf(`const ${name}`)
  if (head < 0)
    return '[]'
  // Search from the `=`, not from the name: a type annotation can carry a
  // bracket of its own (`const LIFE_ACTIONS: LifeAction[] = [`), and
  // starting there would read the type instead of the value.
  const assign = source.indexOf('=', head)
  const open = Math.min(
    ...['[', '{']
      .map(bracket => {
        const at = source.indexOf(bracket, assign)
        return at < 0 ? Number.MAX_SAFE_INTEGER : at
      }),
  )
  if (open === Number.MAX_SAFE_INTEGER)
    return '[]'
  const close = source[open] === '[' ? ']' : '}'
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === source[open])
      depth++
    else if (source[i] === close && --depth === 0)
      return source.slice(open, i + 1).replace(/\/\/[^\n]*/g, '').replace(/\s+/g, ' ')
  }
  return '[]'
}

// Reads the value of a `const NAME = <expression>` out of the
// component.  The expression may carry a type annotation between the
// name and the `=`, which is why this does not simply split on `=`.
function constValue(source, name) {
  const head = source.indexOf(`const ${name}`)
  if (head < 0)
    return undefined
  const assign = source.indexOf('=', head)
  if (assign < 0)
    return undefined
  const rest = source.slice(assign + 1)
  const end = rest.indexOf('\n')
  const value = (end < 0 ? rest : rest.slice(0, end)).trim()
  return value.endsWith(';') ? value.slice(0, -1) : value
}

// Reads a `const NAME = [ ... ]` literal out of the component.
function extractArrayConst(source, name) {
  const head = source.indexOf(`const ${name}`)
  if (head < 0)
    return '[]'
  const open = source.indexOf('[', head)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '[')
      depth++
    else if (source[i] === ']' && --depth === 0)
      return source.slice(open, i + 1).replace(/\/\/[^\n]*/g, '').replace(/\s+/g, ' ')
  }
  return '[]'
}

// The clip is not what reaches the screen.  The component runs every clip
// through `calmClipMotion` first, which pulls each bone's keys towards the
// pose it spends most of its time in.  Measured without it, the idle head
// looks like it swings fourteen degrees -- which is true of the file and
// false of the character.
function applyCalm(clip, keep) {
  const mean = new THREE.Quaternion()
  const key = new THREE.Quaternion()
  const out = new THREE.Quaternion()
  for (const track of clip.tracks) {
    if (!track.name.endsWith('.quaternion'))
      continue
    const factor = keep[track.name.slice(0, -'.quaternion'.length)]
    if (factor === undefined || !(track.values instanceof Float32Array))
      continue
    const values = track.values
    const keys = Math.floor(values.length / 4)
    let x = 0
    let y = 0
    let z = 0
    let w = 0
    let previousX = 0
    let previousY = 0
    let previousZ = 0
    let previousW = 1
    for (let index = 0; index < keys; index++) {
      const at = index * 4
      let qx = values[at]
      let qy = values[at + 1]
      let qz = values[at + 2]
      let qw = values[at + 3]
      if (qx * previousX + qy * previousY + qz * previousZ + qw * previousW < 0) {
        qx = -qx
        qy = -qy
        qz = -qz
        qw = -qw
      }
      previousX = qx
      previousY = qy
      previousZ = qz
      previousW = qw
      x += qx
      y += qy
      z += qz
      w += qw
    }
    mean.set(x, y, z, w).normalize()
    for (let index = 0; index < keys; index++) {
      const at = index * 4
      key.set(values[at], values[at + 1], values[at + 2], values[at + 3])
      out.slerpQuaternions(mean, key, factor)
      values[at] = out.x
      values[at + 1] = out.y
      values[at + 2] = out.z
      values[at + 3] = out.w
    }
  }
}

// Mirrors constantRotationBones in the component: bones the clip never moves
// have to be skipped, because the mixer leaves them alone and the living
// layer would accumulate on top of itself without bound.
function constantRotationBones(clip) {
  const still = new Set()
  for (const track of clip.tracks) {
    if (!track.name.endsWith('.quaternion') || !(track.values instanceof Float32Array))
      continue
    let constant = true
    for (let at = 4; at < track.values.length && constant; at += 4) {
      if (track.values[at] !== track.values[0]
        || track.values[at + 1] !== track.values[1]
        || track.values[at + 2] !== track.values[2]
        || track.values[at + 3] !== track.values[3])
        constant = false
    }
    if (constant)
      still.add(track.name.slice(0, -'.quaternion'.length))
  }
  return still
}

function loadClipCalm(vuePath) {
  const source = readFileSync(vuePath, 'utf8')
  const head = source.indexOf('const CLIP_CALM')
  if (head < 0)
    throw new Error('CLIP_CALM not found')
  const open = source.indexOf('{', head)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{')
      depth++
    else if (source[i] === '}' && --depth === 0) {
      const literal = source.slice(open, i + 1).replace(/\/\/[^\n]*/g, '')
      // The clip table spreads a shared set of bones into every state --
      // the legs, which the living layer drives -- so the shared set is
      // lifted with it and put in scope.
      const shared = extractLiteral(source, 'CALM_LEGS')
      return new Function(`const CALM_LEGS = ${shared};\nreturn ${literal}`)()
    }
  }
  throw new Error('CLIP_CALM is not closed')
}

// Runs one clip for `seconds` at 60Hz and reports the motion of every bone
// named in `watch`.  With `life` on, the same walk the component performs is
// applied on top, so the two runs differ only by the living layer.
function run({ clip, gltf, seconds = 60, watch, life = null, weight = 1, seed = 12345, calmKeep = null, status = 'idle' }) {
  // A fresh rig per run: the mixer leaves whatever pose it last wrote on the
  // bones it bound, and a second run on the same rig would start from that.
  const rig = buildRig(gltf)
  const random = (() => {
    let state = seed >>> 0
    return () => {
      state = (state * 1664525 + 1013904223) >>> 0
      return state / 4294967296
    }
  })()
  // The living layer is lifted out of the component as text and run here,
  // and it draws on the global `Math.random` for every movement it makes.
  // Two runs of the same build are therefore two different performances,
  // and a change to the model cannot be measured against the run before
  // it.  Pointing the global at the seeded generator makes the
  // performance repeatable, so the only thing that differs between two
  // runs is the thing that was changed.
  const realRandom = Math.random
  Math.random = random
  const mixer = new THREE.AnimationMixer(rig.root)
  const action = mixer.clipAction(clip)
  action.play()
  const step = 1 / 60
  // A leading `^` samples the bone in its parent's frame instead of in the
  // world.  That separates "the head moved" from "the body moved and the head
  // came along for the ride", which is the difference between a figure that
  // is shifting its weight and one that is bobbing its head.
  const targets = watch
    .map((entry) => {
      const relative = entry.startsWith('^')
      const node = rig.byName.get(relative ? entry.slice(1) : entry)
      return node ? { node, relative, label: relative ? `rel:${entry.slice(1)}` : entry } : null
    })
    .filter(Boolean)
  const samples = new Map(targets.map(target => [target.label, []]))
  const scratch = new THREE.Quaternion()
  const scratchParent = new THREE.Quaternion()
  // The life layer authors in world axes and carries the result into bone
  // space, so the probe has to keep the same rest-parent frames the component
  // captured at load time.
  const frames = new Map()
  if (life) {
    for (const item of life.bones) {
      const node = rig.byName.get(item.bone)
      if (!node)
        continue
      const restParent = chainWorldQuaternion(node.parent, new THREE.Quaternion())
      frames.set(item.bone, {
        node,
        restWorld: chainWorldQuaternion(node, new THREE.Quaternion()),
        restParent,
        restParentInv: restParent.clone().invert(),
        stabilise: item.bone === 'halo',
        ownedBy: '',
        base: new THREE.Quaternion(),
        spec: item,
      })
    }
  }
  let move = null
  let nextMoveAt = 4.5
  const postureSample = new THREE.Vector3()
  const headFlowSample = new THREE.Quaternion()
  const stillBones = constantRotationBones(clip)
  // A bone the clip has been stripped of entirely is now a constant track,
  // so it shows up in `stillBones` -- but the component hands those bones
  // to the living layer outright, because nothing else drives them.
  const ownedBones = new Set(
    Object.entries(calmKeep?.[clip.name] ?? {})
      .filter(([, factor]) => factor === 0)
      .map(([bone]) => bone),
  )
  if (args.debug)
    console.log(`  ${clip.name}: clip holds still -- ${[...stillBones].sort().join(', ') || '(none)'}`)
  const euler = new THREE.Euler()
  const world = new THREE.Quaternion()
  const local = new THREE.Quaternion()
  const offset = new THREE.Vector3()
  const parentWorld = new THREE.Quaternion()
  // Per-frame record of everything the living layer writes, so a
  // discontinuity can be traced to the quantity that caused it instead of
  // guessed at.  Only the window asked for is kept, because a whole run of
  // this is tens of megabytes.
  const frameFrom = args.frameFrom === undefined ? -1 : Number(args.frameFrom)
  const frameTo = args.frameTo === undefined ? -1 : Number(args.frameTo)
  const frameRecord = []

  const traced = args.trace ? rig.byName.get(args.trace) : null
  const probed = args.mixer ? rig.byName.get(args.mixer) : null
  const trace = []
  for (let frame = 0; frame < seconds * 60; frame++) {
    const time = frame * step
    const before = frame < 4 && probed
      ? [probed.quaternion.x, probed.quaternion.y, probed.quaternion.z, probed.quaternion.w].map(v => v.toFixed(4)).join(', ')
      : null
    mixer.update(step)
    if (frame < 4 && probed)
      console.log(`    f${frame} before: ${before}   after: ${[probed.quaternion.x, probed.quaternion.y, probed.quaternion.z, probed.quaternion.w].map(v => v.toFixed(4)).join(', ')}`)
    if (frame === 0 && args.chain) {
      let node = rig.byName.get(args.chain)
      const chain = []
      while (node) {
        chain.push(node)
        node = node.parent
      }
      console.log(`\n  chain ${args.chain}`)
      for (const link of chain.reverse()) {
        const q = link.quaternion
        console.log(`    ${(link.name || '(unnamed)').padEnd(22)}`
          + ` |q| ${Math.hypot(q.x, q.y, q.z, q.w).toFixed(5)}`
          + `  ${[q.x, q.y, q.z, q.w].map(v => v.toFixed(4)).join(', ')}`)
      }
    }
    if (life) {
      life.updateAttention(time, status)
      life.updateMotionLevels(time)
      if (args.attention && frame % 30 === 0) {
        console.log(`    t=${time.toFixed(1).padStart(5)}`
          + `  target yaw/pitch/roll ${life.attention.yaw.toFixed(1)}`
          + `/${life.attention.pitch.toFixed(1)}/${life.attention.roll.toFixed(1)}`
          + `   now ${life.attentionNow.yaw.toFixed(1)}`
          + `/${life.attentionNow.pitch.toFixed(1)}/${life.attentionNow.roll.toFixed(1)}`)
      }
      if (!move && time >= nextMoveAt) {
        const action = life.pickLifeAction(status)
        move = { action, start: time, side: random() < 0.5 ? -1 : 1 }
        life.history.push(action.kind)
        if (args.actions)
          console.log(`    t=${time.toFixed(1).padStart(6)}  action ${action.kind}`)
        if (life.history.length > 8)
          life.history.shift()
        nextMoveAt = time + action.dur + life.nextLifeGap()
      }
      // Sized by the whole living layer and not by the bones being
      // watched: the movement in progress writes into the slot of the
      // bone it names, and that slot is the bone's index in the living
      // layer.  Sizing this by the watched bones silently dropped every
      // movement on a bone that came after the last watched one.
      const moveDeg = new Float32Array(life.bones.length * 3)
      let moveKind = ''
      let moveAmount = 0
      let moveK = 0
      if (move) {
        const k = (time - move.start) / move.action.dur
        moveKind = move.action.kind
        moveK = k
        if (k >= 1) {
          move = null
        }
        else {
          const amount = life.actionEnvelope(k, move.action)
          moveAmount = amount
          for (const channel of move.action.channels) {
            const index = life.boneIndex.get(channel.bone)
            if (index === undefined)
              continue
            const side = channel.side === undefined || channel.side === 0 ? move.side : channel.side
            moveDeg[index * 3 + channel.axis] += channel.deg * amount * side
          }
        }
      }
      for (const [name, entry] of frames) {
        const owned = ownedBones.has(name)
        if (!entry.stabilise && !owned && stillBones.has(name))
          continue
        const index = life.boneIndex.get(name)
        const { spec } = entry
        life.samplePosture(time - spec.lag, postureSample, spec.cell)
        const breath = life.lifeBreath(time)
        const weightShift = life.lifeWeight(time)
        const tremor = life.lifeMicro(time, spec.phase) * spec.micro
        // The lean.
        const chain = spec.drive === 'body' ? spec.gain : 0
        offset.set(
          (spec.drift * life.lifeDrift(time, spec.rate, spec.phase, 0)
            + (spec.drive === 'body' ? 0 : postureSample.x * spec.gain)
            + tremor
            + breath * spec.breath) * weight,
          (spec.drift * life.lifeDrift(time, spec.rate, spec.phase, 1)
            + (spec.drive === 'body' ? 0 : postureSample.y * spec.gain)) * weight,
          (spec.drift * life.lifeDrift(time, spec.rate, spec.phase, 2)
            + (spec.drive === 'body' ? 0 : postureSample.z * spec.gain)) * weight,
        )
        if (chain !== 0) {
          const lean = life.motionChainLean()
          offset.x += lean.x * chain * weight
          offset.y += lean.y * chain * weight
          offset.z += lean.z * chain * weight
        }
        if (name === 'hips') {
          const root = life.motionRootLean()
          offset.x += root.x * weight
          offset.y += root.y * weight
          offset.z += root.z * weight
        }
        const sway = life.weightSway[name]
        if (sway) {
          offset.x += sway.pitch * weightShift
          offset.y += sway.yaw * weightShift
          offset.z += sway.roll * weightShift
        }
        if (index !== undefined) {
          offset.x += moveDeg[index * 3] * weight
          offset.y += moveDeg[index * 3 + 1] * weight
          offset.z += moveDeg[index * 3 + 2] * weight
        }
        if (spec.follow > 0)
          offset.y += life.attentionNow.yaw * spec.follow * (life.attentionGain[status] ?? 1)
        // The body carries the head: every bone takes a share of the
        // head's own slow movement, so the figure moves as one piece.
        if (spec.lead) {
          const sway = life.headSway()
          offset.x += sway.x * spec.lead
          offset.z += sway.z * spec.lead
        }
        if (name === 'head') {
          // The head is solved for: the world rotation it has to end
          // up in is known, and the bone is given whatever turns it
          // into that from where its parent is right now.
          const aim = life.attentionGain[status] ?? 1
          // And the head takes the torso's share of a gesture, so that a
          // lean carries the head instead of stopping at the shoulders.
          let inheritPitch = 0
          let inheritYaw = 0
          let inheritRoll = 0
          for (const chainBone of ['hips', 'spine', 'chest', 'upperChest']) {
            const chainIndex = life.boneIndex.get(chainBone)
            if (chainIndex === undefined)
              continue
            inheritPitch += moveDeg[chainIndex * 3]
            inheritYaw += moveDeg[chainIndex * 3 + 1]
            inheritRoll += moveDeg[chainIndex * 3 + 2]
          }
          life.updateHeadShape(
            time,
            status,
            headFlowSample,
            moveDeg[index === undefined ? 0 : index * 3] * weight + inheritPitch * weight,
            moveDeg[index === undefined ? 0 : index * 3 + 1] * weight + inheritYaw * weight,
            moveDeg[index === undefined ? 0 : index * 3 + 2] * weight + inheritRoll * weight,
          )
          if (owned && entry.ownedBy !== clip.name) {
            entry.base.copy(entry.node.quaternion)
            entry.ownedBy = clip.name
          }
          const base = owned ? entry.base : entry.node.quaternion
          chainWorldQuaternion(entry.node.parent, parentWorld)
          local
            .copy(parentWorld)
            .invert()
            .multiply(headFlowSample)
            .multiply(entry.restParent)
            .multiply(base)
          entry.node.quaternion.copy(local)
          continue
        }
        const recording = frameFrom >= 0 && frame >= frameFrom && frame <= frameTo
        if (recording) {
          frameRecord.push({
            frame,
            bone: name,
            offset: [+offset.x.toFixed(4), +offset.y.toFixed(4), +offset.z.toFixed(4)],
            move: index === undefined
              ? [0, 0, 0]
              : [+moveDeg[index * 3].toFixed(4), +moveDeg[index * 3 + 1].toFixed(4), +moveDeg[index * 3 + 2].toFixed(4)],
            posture: [+postureSample.x.toFixed(4), +postureSample.y.toFixed(4), +postureSample.z.toFixed(4)],
            weight: +weightShift.toFixed(4),
            action: moveKind,
            amount: +moveAmount.toFixed(4),
            k: +moveK.toFixed(4),
            breath: +breath.toFixed(4),
            tremor: +tremor.toFixed(4),
            attention: [
              +life.attentionNow.yaw.toFixed(4),
              +life.attentionNow.pitch.toFixed(4),
              +life.attentionNow.roll.toFixed(4),
            ],
            sway: sway
              ? [+sway.pitch.toFixed(4), +sway.yaw.toFixed(4), +sway.roll.toFixed(4)]
              : [0, 0, 0],
            local: entry.node.quaternion.toArray().map(v => +v.toFixed(5)),
          })
        }
        euler.set(
          THREE.MathUtils.degToRad(offset.x),
          THREE.MathUtils.degToRad(offset.y),
          THREE.MathUtils.degToRad(offset.z),
        )
        if (args.jump && name === args.jump) {
          const rate = 60
          const at = Math.round(Number(args.jumpAt ?? 0) * rate)
          if (Math.abs(frame - at) < 8) {
            console.log(`    ${args.jump} f${frame} offset ${offset.x.toFixed(2)}/${offset.y.toFixed(2)}/${offset.z.toFixed(2)}`
              + ` posture ${postureSample.x.toFixed(3)}/${postureSample.y.toFixed(3)}/${postureSample.z.toFixed(3)}`
              + ` move ${moveDeg[index === undefined ? 0 : index * 3].toFixed(2)}`
              + ` q ${entry.node.quaternion.toArray().map(v => v.toFixed(4)).join(',')}`)
          }
        }
        world.setFromEuler(euler)
        if (entry.stabilise && entry.node.parent) {
          chainWorldQuaternion(entry.node.parent, parentWorld)
          local.copy(parentWorld).invert().multiply(entry.restWorld).multiply(world)
          entry.node.quaternion.copy(local)
        }
        else {
          local.copy(entry.restParentInv).multiply(world).multiply(entry.restParent)
          if (owned) {
            if (entry.ownedBy !== clip.name) {
              entry.base.copy(entry.node.quaternion)
              entry.ownedBy = clip.name
            }
            entry.node.quaternion.copy(entry.base).premultiply(local)
          }
          else {
            entry.node.quaternion.premultiply(local)
          }
        }
      }
    }
    for (const target of targets) {
      chainWorldQuaternion(target.node, scratch)
      if (target.relative && target.node.parent)
        scratch.premultiply(chainWorldQuaternion(target.node.parent, scratchParent).invert())
      samples.get(target.label).push(scratch.clone())
    }
    if (args.euler && frame % 30 === 0) {
      const node = rig.byName.get(args.euler)
      if (node) {
        chainWorldQuaternion(node, scratch)
        const e = new THREE.Euler().setFromQuaternion(scratch, 'XYZ')
        console.log(`    t=${time.toFixed(1).padStart(5)}`
          + `  ${args.euler} world euler`
          + ` ${(e.x * DEG).toFixed(2)}/${(e.y * DEG).toFixed(2)}/${(e.z * DEG).toFixed(2)}`
          + `   attention ${life ? life.attentionNow.yaw.toFixed(1) : '-'}`
          + `/${life ? life.attentionNow.pitch.toFixed(1) : '-'}`
          + `/${life ? life.attentionNow.roll.toFixed(1) : '-'}`)
      }
    }
    if (traced)
      trace.push(chainWorldQuaternion(traced, scratch.clone()).clone())
  }
  mixer.stopAllAction()
  const out = new Map()
  for (const [name, series] of samples) {
    const stats = describe(series)
    if (stats)
      out.set(name, stats)
  }
  if (trace.length > 0) {
    console.log(`\n  trace ${args.trace}`)
    const every = Math.max(1, Math.floor(trace.length / 24))
    const origin = trace[0]
    for (let i = 0; i < trace.length; i += every) {
      const q = trace[i]
      // Angle from the first sample rather than Euler angles: these chains
      // pass through gimbal lock, where the Euler triple jumps by ninety
      // degrees while the rotation does not move at all.
      const angle = 2 * Math.acos(Math.min(1, Math.abs(q.dot(origin)))) * DEG
      console.log(`    t=${(i / 60).toFixed(1).padStart(5)}  ${angle.toFixed(1).padStart(7)} deg from start`
        + `  |q| ${(Math.hypot(q.x, q.y, q.z, q.w)).toFixed(4)}`)
    }
  }
  out.series = samples
  if (frameRecord.length > 0) {
    const target = resolve(args.frames)
    mkdirSync(dirname(target), { recursive: true })
    writeFileSync(target, JSON.stringify(frameRecord))
    console.log(`\n  wrote ${args.frames} (${frameRecord.length} records)`)
  }
  Math.random = realRandom
  return out
}

function smoothstep(value) {
  const k = Math.min(1, Math.max(0, value))
  return k * k * (3 - 2 * k)
}

const DEFAULT_WATCH = [
  'head',
  'neck',
  'upperChest',
  'chest',
  'spine',
  'hips',
  'halo',
  'wing.L',
  'leftUpperArm',
]

function parseArgs(argv) {
  const args = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]
    if (!token.startsWith('--')) {
      args._.push(token)
      continue
    }
    const next = argv[i + 1]
    // A flag with no value is a switch; one followed by a word takes it.
    if (next === undefined || next.startsWith('--'))
      args[token.slice(2)] = true
    else {
      args[token.slice(2)] = next
      i++
    }
  }
  return args
}

function report(title, stats, order) {
  console.log(`\n${title}`)
  console.log('  bone           spread   deg/10s   still%   held%  busy%   moves   lag6    axis sd x/y/z    axis corr xy/xz/yz')
  for (const name of order) {
    const row = stats.get(name.startsWith('^') ? `rel:${name.slice(1)}` : name)
    if (!row)
      continue
    console.log(
      `  ${name.padEnd(14)}${String(row.spread).padStart(6)}`
      + `${String(row.speed).padStart(10)}${String(row.quiet).padStart(8)}`
      + `${String(row.held).padStart(8)}${String(row.moving).padStart(8)}`
      + `${String(row.episodes).padStart(8)}`
      + `${String(row.lag).padStart(9)}`
      + `     ${`${row.axes.x}/${row.axes.y}/${row.axes.z}`.padEnd(16)}`
      + `${`${row.axes.cxy}/${row.axes.cxz}/${row.axes.cyz}`.padEnd(17)}`,
    )
    if (args.verbose)
      console.log(`       worst at t=${row.spreadAt}s   p10/50/90 = ${row.percentiles.join(' / ')} deg`)
  }
}

// The series itself, so the motion can be looked at rather than only
// summarised.  Each bone is written as three world-axis degrees measured
// against its own first sample, at 10Hz -- plenty for a filmstrip, and
// small enough to diff between two runs of the same component.
function dumpSeries(file, series, seconds, status) {
  const step = 6
  const out = { seconds, status, rate: 10, bones: {} }
  const q = new THREE.Quaternion()
  for (const [name, samples] of series) {
    if (!samples?.length)
      continue
    const origin = samples[0].clone().invert()
    const deviation = new THREE.Quaternion()
    const axes = [[], [], []]
    const steps = []
    let previous = samples[0]
    for (let i = 0; i < samples.length; i += step) {
      // The rotation vector, not an Euler triple.  An extracted XYZ triple
      // can add up to far more than the angle it represents once the axes
      // are mixed, which paints spikes onto a trace that has none, and a
      // spike in a picture of a head's motion is indistinguishable from a
      // twitch.
      deviation.copy(origin).multiply(samples[i])
      // The rotation-vector scaling, done the same way `describe` does it:
      // from the angle rather than from the raw Euler triple, whose length
      // goes to zero at identity and would amplify sampling noise by six
      // orders of magnitude.
      const w = Math.min(1, Math.abs(deviation.w))
      const angle = 2 * Math.acos(w)
      const sin = Math.sqrt(Math.max(1e-12, 1 - w * w))
      const scale = sin > 1e-9 ? angle / sin : 0
      axes[0].push(+(deviation.x * scale * DEG).toFixed(3))
      axes[1].push(+(deviation.y * scale * DEG).toFixed(3))
      axes[2].push(+(deviation.z * scale * DEG).toFixed(3))
      if (i > 0) {
        const seconds = step / 60
        steps.push(+(
          2 * Math.acos(Math.min(1, Math.abs(samples[i].dot(previous)))) * DEG / seconds
        ).toFixed(2))
      }
      previous = samples[i]
    }
    out.bones[name] = { x: axes[0], y: axes[1], z: axes[2], step: steps }
  }
  const target = resolve(file)
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, JSON.stringify(out))
  console.log(`\n  wrote ${file}`)
}

const args = parseArgs(process.argv.slice(2))
const vrm = args.vrm ?? args._[0]
if (!vrm) {
  console.error('usage: node scripts/probe_yxz_motion.mjs --vrm <file> [--clip <name>] [--life <scene.vue>] [--seconds 60]')
  process.exit(1)
}
const seconds = Number(args.seconds ?? 60)
const { json, bin } = readGlb(vrm)
const rig = buildRig(json)
const clips = buildClips(json, accessorReader(json, bin))
const life = args.life ? loadLifeLayer(args.life) : null
const watch = (args.watch ?? DEFAULT_WATCH.join(',')).split(',')
const calm = args.calm ? loadClipCalm(args.calm) : null

console.log(`${basename(vrm)}  ${json.nodes?.length ?? 0} nodes  ${clips.length} clips`)
const chosen = args.clip
  ? clips.filter(clip => clip.name === args.clip)
  : clips
if (chosen.length === 0) {
  console.error(`no clip matched ${args.clip}. available: ${clips.map(c => c.name).join(', ')}`)
  process.exit(1)
}
if (args.debug) {
  for (const clip of chosen) {
    const rotations = clip.tracks.filter(t => t.name.endsWith('.quaternion'))
    console.log(`  ${clip.name}: ${clip.tracks.length} tracks, ${rotations.length} rotation, `
      + `duration ${clip.duration}`)
    for (const track of rotations.slice(0, 4)) {
      const mid = Math.floor(track.values.length / 8) * 4
      console.log(`    ${track.name}  keys ${track.times.length} last ${track.times[track.times.length - 1]}  `
        + `first ${Array.from(track.values.slice(0, 4)).map(v => v.toFixed(3)).join(',')}  `
        + `mid ${Array.from(track.values.slice(mid, mid + 4)).map(v => v.toFixed(3)).join(',')}`)
    }
    for (const track of clip.tracks) {
      if (!track.name.startsWith(`${args.dumpTrack}.`))
        continue
      console.log(`    ${track.name}: ${track.times.length} keys, `
        + `${track.values.length} values`)
      console.log(`      times ${Array.from(track.times).map(v => v.toFixed(3)).join(' ')}`)
      console.log(`      vals  ${Array.from(track.values).map(v => v.toFixed(4)).join(' ')}`)
    }
  }
}

for (const clip of chosen) {
  // The clip is mutated in place, so a calmed run gets its own copy.
  const source = calm
    ? new THREE.AnimationClip(clip.name, -1, clip.tracks.map(track => track.clone()))
    : clip
  if (calm)
    applyCalm(source, calm[clip.name] ?? {})
  const seed = Number(args.seed ?? 12345)
  const bare = run({ clip: source, gltf: json, seconds, watch, seed })
  report(`${clip.name}  (${calm ? 'clip as shipped' : 'raw clip'}, ${seconds}s)`, bare, watch)
  // The bare series is dumped next to the layered one so that a clip can be
  // compared against a reference on the same axes.  `idle_loop.vrma` is the
  // reference: the airi girl's own idle, and the thing the YXZ motion is
  // being measured against.
  if (args.dump)
    dumpSeries(`${args.dump}/${clip.name}-bare.json`, bare.series, seconds, args.status ?? 'idle')
  if (life) {
    // Every run starts from a clean history, so the character does not
    // remember what it did during the previous run.
    life.history.length = 0
    life.resetAttention()
    life.gapState.lifeBurstLeft = 0
    const layered = run({ clip: source, gltf: json, seconds, watch, life, calmKeep: calm, status: args.status ?? 'idle', seed })
    report(`${clip.name}  (clip + living layer, ${args.status ?? 'idle'})`, layered, watch)
    console.log(`  small head movements: ${life.gestureCount()}`
      + `  (${(life.gestureCount() / (seconds / 60)).toFixed(1)} a minute)`)
    if (args.dump)
      dumpSeries(`${args.dump}/${clip.name}.json`, layered.series, seconds, args.status ?? 'idle')
  }
}
