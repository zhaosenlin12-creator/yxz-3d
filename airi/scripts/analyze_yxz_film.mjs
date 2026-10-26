/**
 * Read a film's trace and say what the film is doing.
 *
 * Three questions, all of them about the figure as one object:
 *
 *   travel    how far each bone actually travels, in degrees.  A bone
 *             that travels a lot is a bone the eye will follow.
 *   coherence how much of the head's travel the body shares.  A head
 *             that moves while the chest does not is a puppet with a
 *             face on it.
 *   closing   whether the head's aim describes a closed loop.  A closed
 *             loop is what the eye cannot stop watching, and it is
 *             what "circling" means.
 *
 * Usage: node scripts/analyze_yxz_film.mjs docs/yxz-audit/film-r161
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'

function quatToVec(q) {
  const [x, y, z, w] = q
  const s = w < 0 ? -1 : 1
  return [x * s, y * s, z * s, w * s]
}

function quatAngle(a, b) {
  const [ax, ay, az, aw] = a
  const [bx, by, bz, bw] = b
  const dot = Math.abs(ax * bx + ay * by + az * bz + aw * bw)
  return 2 * Math.acos(Math.min(1, dot)) * 180 / Math.PI
}

function quatMul(a, b) {
  const [ax, ay, az, aw] = a
  const [bx, by, bz, bw] = b
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ]
}

function quatConj(q) {
  return [-q[0], -q[1], -q[2], q[3]]
}

/** The rotation that takes `a` onto `b`. */
function quatDelta(a, b) {
  return quatMul(b, quatConj(a))
}

/** The axis-angle of a quaternion, in degrees. */
function quatAxisAngle(q) {
  const [x, y, z, w] = quatToVec(q)
  const angle = 2 * Math.acos(Math.min(1, Math.abs(w)))
  const sin = Math.sin(angle / 2)
  if (Math.abs(sin) < 1e-9)
    return { angle: 0, axis: [0, 0, 1] }
  return { angle: angle * 180 / Math.PI, axis: [x / sin, y / sin, z / sin] }
}

function deviation(values) {
  // Averaging quaternions directly is wrong here, and wrong in a way
  // that hides rather than shows: this rig rests several of its bones
  // at half a turn, so neighbouring samples can sit on either side of
  // the sign boundary and their average cancels to nothing.  The
  // deviations are measured against the first sample instead, which
  // keeps every increment small and near the identity, where an
  // average means what it says.
  const reference = values[0]
  const deltas = values.map(q => quatDelta(reference, q))
  let sum = [0, 0, 0, 0]
  for (const d of deltas) {
    const v = quatToVec(d)
    for (let i = 0; i < 4; i++)
      sum[i] += v[i]
  }
  const len = Math.hypot(...sum)
  const meanDelta = len > 1e-9 ? sum.map(v => v / len) : [0, 0, 0, 1]
  const mean = quatMul(meanDelta, reference)
  let max = 0
  for (const d of deltas)
    max = Math.max(max, quatAngle(d, meanDelta))
  return { mean, max }
}

/** Pearson correlation of two series. */
function correlation(a, b) {
  const n = Math.min(a.length, b.length)
  if (n < 3)
    return 0
  const mean = (list) => list.reduce((s, v) => s + v, 0) / list.length
  const ma = mean(a.slice(0, n))
  const mb = mean(b.slice(0, n))
  let num = 0
  let da = 0
  let db = 0
  for (let i = 0; i < n; i++) {
    const x = a[i] - ma
    const y = b[i] - mb
    num += x * y
    da += x * x
    db += y * y
  }
  if (da < 1e-12 || db < 1e-12)
    return 0
  return num / Math.sqrt(da * db)
}

const dir = process.argv[2]
if (!dir)
  throw new Error('usage: node scripts/analyze_yxz_film.mjs <film dir>')
const trace = JSON.parse(readFileSync(path.join(dir, 'trace.json'), 'utf8')).trace

const names = new Set()
for (const frame of trace)
  for (const name of Object.keys(frame.bones))
    names.add(name)

console.log(`frames: ${trace.length}`)
console.log(`model time: ${trace[0]?.modelTime.toFixed(2)}s -> ${trace.at(-1)?.modelTime.toFixed(2)}s`)
console.log('')
console.log('bone            travel°   per-frame°   pitch°   yaw°   roll°')

const series = new Map()
for (const name of names) {
  const quats = trace.map(f => f.bones[name]).filter(Boolean)
  if (quats.length < 2)
    continue
  series.set(name, quats)
  const { max } = deviation(quats)
  // The swing of each axis, measured against the mean pose.
  const { mean } = deviation(quats)
  let swing = [0, 0, 0]
  for (const q of quats) {
    const { angle, axis } = quatAxisAngle(quatDelta(mean, q))
    for (let i = 0; i < 3; i++)
      swing[i] = Math.max(swing[i], Math.abs(axis[i] * angle))
  }
  const perFrame = []
  for (let i = 1; i < quats.length; i++)
    perFrame.push(quatAngle(quats[i - 1], quats[i]))
  const meanStep = perFrame.reduce((s, v) => s + v, 0) / perFrame.length
  console.log(
    `${name.padEnd(14)} ${max.toFixed(2).padStart(7)}   ${meanStep.toFixed(3).padStart(8)}`
    + `   ${swing[0].toFixed(2).padStart(6)}  ${swing[1].toFixed(2).padStart(5)}  ${swing[2].toFixed(2).padStart(5)}`,
  )
}

// Coherence: how much of the head's travel the chest shares.
const head = series.get('head')
const chest = series.get('upperChest') ?? series.get('chest')
if (head && chest) {
  const headSteps = []
  const chestSteps = []
  for (let i = 1; i < Math.min(head.length, chest.length); i++) {
    headSteps.push(quatAngle(head[i - 1], head[i]))
    chestSteps.push(quatAngle(chest[i - 1], chest[i]))
  }
  console.log('')
  console.log(`head/chest step correlation: ${correlation(headSteps, chestSteps).toFixed(3)}`)
  // The head's travel relative to the chest: the part of the head's
  // movement that the body is not carrying.
  const relative = []
  for (let i = 0; i < Math.min(head.length, chest.length); i++)
    relative.push(quatMul(head[i], quatConj(chest[i])))
  const { max } = deviation(relative)
  console.log(`head travel relative to chest: ${max.toFixed(2)}°`)
}

// Closing: whether the head's aim comes back to where it started.
if (head && head.length > 3) {
  const first = head[0]
  const last = head.at(-1)
  const travelled = deviation(head).max
  const closed = quatAngle(first, last)
  console.log('')
  console.log(`head travelled ${travelled.toFixed(2)}°, ended ${closed.toFixed(2)}° from where it started`)
  console.log(`closing ratio: ${(closed / Math.max(travelled, 1e-6)).toFixed(3)}  (small = the path closes on itself)`)
}
