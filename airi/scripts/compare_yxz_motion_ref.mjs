/**
 * Compare the YXZ head motion against the airi girl's, on the same axes.
 *
 * The summaries that already exist answer "how far does the head move"
 * and "does it come back to the same pose".  Neither answers the question
 * that is actually being asked, which is "does it look like a person
 * standing there or does it look like a mechanism".
 *
 * The difference between those two is structural, and it has three parts:
 *
 *   ellipse   How strongly the two visible axes move together.  A head
 *             that rocks and tilts in step traces a diagonal line.  A head
 *             that does the same thing two hundred times over two minutes
 *             traces an ellipse, and an ellipse is a circle in the plane
 *             of the face, and a circle is the one shape the eye cannot
 *             stop watching.  This is the "circling" number.
 *
 *   episodes  How the motion is chunked.  A person does a thing, holds
 *             still, and then does another thing.  A mechanism does one
 *             continuous thing forever.  The count and the shape of the
 *             chunks is the difference between "idle" and "idle loop".
 *
 *   texture   How much of the motion is fast.  A drift is a sway.  A
 *             movement with a fast edge and a slow middle is a gesture.
 *             The airi girl's head has about a ninth of its power above
 *             0.4Hz and it is that fast edge that makes her look awake.
 *
 * Usage:
 *   node scripts/compare_yxz_motion_ref.mjs <ref.json> <current.json>
 */

import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

const DEG = 180 / Math.PI

function load(file) {
  const json = JSON.parse(readFileSync(file, 'utf8'))
  const rate = json.rate ?? 10
  const bone = json.bones?.head
  if (!bone)
    throw new Error(`${file}: no head bone`)
  return { name: basename(file), rate, head: bone }
}

function mean(values) {
  return values.reduce((a, b) => a + b, 0) / Math.max(1, values.length)
}

function sd(values) {
  const m = mean(values)
  return Math.sqrt(mean(values.map(v => (v - m) ** 2)))
}

function corr(a, b) {
  const ma = mean(a)
  const mb = mean(b)
  let num = 0
  let da = 0
  let db = 0
  for (let i = 0; i < a.length; i++) {
    const x = a[i] - ma
    const y = b[i] - mb
    num += x * y
    da += x * x
    db += y * y
  }
  return da * db > 1e-12 ? num / Math.sqrt(da * db) : 0
}

// Variance by frequency band, over the head's dominant plane.
function bands(values, rate) {
  const n = values.length
  const centred = values.map(v => v - mean(values))
  const edges = [0, 0.05, 0.15, 0.4, rate / 2]
  const out = edges.slice(0, -1).map(() => 0)
  for (let k = 1; k < Math.floor(n / 2); k++) {
    const freq = k / n * rate
    let re = 0
    let im = 0
    for (let i = 0; i < n; i++) {
      const angle = 2 * Math.PI * k * i / n
      re += centred[i] * Math.cos(angle)
      im -= centred[i] * Math.sin(angle)
    }
    const power = (re * re + im * im) / n
    for (let b = 0; b < out.length; b++) {
      if (freq >= edges[b] && freq < edges[b + 1])
        out[b] += power
    }
  }
  const total = out.reduce((a, b) => a + b, 0) || 1
  return out.map(v => +(v / total).toFixed(3))
}

// The autocorrelation peak that is not the trivial one.
function dominantPeriod(values, rate) {
  const minLag = Math.round(rate)
  const maxLag = Math.min(values.length - 2, Math.round(rate * 25))
  const centred = values.map(v => v - mean(values))
  const at = (lag) => {
    let num = 0
    let den = 0
    for (let i = 0; i + lag < centred.length; i++) {
      num += centred[i] * centred[i + lag]
      den += centred[i] * centred[i]
    }
    return den > 1e-12 ? num / den : 0
  }
  let best = { period: 0, peak: -2 }
  for (let lag = minLag; lag <= maxLag; lag++) {
    const value = at(lag)
    if (value > at(lag - 1) && value >= at(lag + 1) && value > best.peak)
      best = { period: +(lag / rate).toFixed(2), peak: +value.toFixed(3) }
  }
  return best
}

// The motion as chunks.
//
// A frame where the head moved more than the threshold opens a chunk and
// it closes when the head stops moving.  What is left is the list of
// things the character did, which is the only description of an idle that
// anybody can act on: how many, how big, how long.
function episodes(head, rate) {
  const step = Math.max(1, Math.round(rate / 10))
  const half = Math.max(1, Math.round(rate * 0.5))
  const points = []
  for (let i = 0; i < head.x.length; i += step)
    points.push([head.x[i], head.z[i]])
  const rate2 = rate / step
  const chunks = []
  let open = null
  for (let i = 1; i < points.length; i++) {
    const moved = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
    const fast = moved / (step / rate) > 0.6
    if (fast && !open)
      open = { from: i, to: i, peak: 0 }
    if (open) {
      open.to = i
      open.peak = Math.max(open.peak, moved)
    }
    if (!fast && open) {
      const duration = (open.to - open.from) / rate2
      if (duration > 0.25)
        chunks.push({ duration, peak: +(open.peak / (step / rate)).toFixed(2) })
      open = null
    }
  }
  if (open) {
    const duration = (open.to - open.from) / rate2
    if (duration > 0.25)
      chunks.push({ duration, peak: +(open.peak / (step / rate)).toFixed(2) })
  }
  const durations = chunks.map(c => c.duration).sort((a, b) => a - b)
  const peaks = chunks.map(c => c.peak).sort((a, b) => a - b)
  const mid = (arr) => (arr.length ? arr[Math.floor(arr.length / 2)] : 0)
  return {
    count: chunks.length,
    perMinute: +((chunks.length / (head.x.length / rate)) * 60).toFixed(1),
    medianDuration: +mid(durations).toFixed(2),
    medianPeak: +mid(peaks).toFixed(2),
  }
}

// The largest single step the head takes.
//
// Everything else here describes the shape of the motion.  This
// describes its edges: a head that is doing something ordinary but
// occasionally jumps a degree in one frame reads as broken, however
// good the shape between the jumps is.  The reference never takes a
// step like that, and neither should this.
function snaps(head, rate) {
  const step = Math.max(1, Math.round(rate / 10))
  const points = []
  for (let i = 0; i < head.x.length; i += step)
    points.push([head.x[i], head.z[i]])
  const seconds = step / rate
  const rates = []
  for (let i = 1; i < points.length; i++) {
    rates.push(Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]) / seconds)
  }
  rates.sort((a, b) => a - b)
  const at = (p) => +(rates[Math.min(rates.length - 1, Math.floor(p * rates.length))] ?? 0).toFixed(2)
  return { p99: at(0.99), max: +(rates.at(-1) ?? 0).toFixed(2) }
}

function describe(file) {
  const { name, rate, head } = load(file)
  const window = Math.max(1, Math.round(rate * 0.5))
  let held = 0
  let counted = 0
  for (let i = window; i < head.x.length; i++) {
    counted++
    const moved = Math.hypot(head.x[i] - head.x[i - window], head.z[i] - head.z[i - window])
    if (moved < 0.4)
      held++
  }
  // The path length of the head in the plane of the face.
  let path = 0
  for (let i = 1; i < head.x.length; i++)
    path += Math.hypot(head.x[i] - head.x[i - 1], head.z[i] - head.z[i - 1])
  const seconds = head.x.length / rate
  return {
    name,
    seconds: +seconds.toFixed(0),
    sd: [+sd(head.x).toFixed(2), +sd(head.y).toFixed(2), +sd(head.z).toFixed(2)],
    // The ellipse number: how strongly the two visible axes move together.
    ellipse: +corr(head.x, head.z).toFixed(3),
    yawEllipse: +corr(head.x, head.y).toFixed(3),
    held: Math.round((held / Math.max(1, counted)) * 100),
    pathPerSec: +(path / seconds).toFixed(2),
    period: dominantPeriod(head.x, rate),
    bands: bands(head.x, rate),
    episodes: episodes(head, rate),
    snaps: snaps(head, rate),
  }
}

const files = process.argv.slice(2)
if (files.length < 2) {
  console.error('usage: node scripts/compare_yxz_motion_ref.mjs <ref.json> <current.json>')
  process.exit(1)
}

const rows = files.map(describe)
console.log('metric'.padEnd(22) + rows.map(r => r.name.slice(0, 22).padStart(24)).join(''))
const line = (label, values) =>
  console.log(label.padEnd(22) + values.map(v => String(v).padStart(24)).join(''))
line('sd pitch/yaw/roll', rows.map(r => r.sd.join(' / ')))
line('ellipse pitch~roll', rows.map(r => r.ellipse))
line('ellipse pitch~yaw', rows.map(r => r.yawEllipse))
line('held %', rows.map(r => r.held))
line('path deg/s', rows.map(r => r.pathPerSec))
line('dominant period s', rows.map(r => r.period.period))
line('  autocorr peak', rows.map(r => r.period.peak))
line('bands drift', rows.map(r => r.bands[0]))
line('bands settle', rows.map(r => r.bands[1]))
line('bands wobble', rows.map(r => r.bands[2]))
line('bands fast', rows.map(r => r.bands[3]))
line('episodes count', rows.map(r => r.episodes.count))
line('episodes /min', rows.map(r => r.episodes.perMinute))
line('episode med dur s', rows.map(r => r.episodes.medianDuration))
line('episode med peak d/s', rows.map(r => r.episodes.medianPeak))
line('snap p99 d/s', rows.map(r => r.snaps.p99))
line('snap max d/s', rows.map(r => r.snaps.max))
