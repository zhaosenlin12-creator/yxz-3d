// Motion texture.
//
// The probe measures how much a bone moves.  It does not measure what the
// movement *is*, and the difference is the whole of the complaint: a head
// can move eight degrees a second and still read as calm, and a head can
// move two degrees a second and read as a metronome.  What separates them
// is the texture of the signal:
//
//   period   how close the pose at t is to the pose at t + P.  A figure on
//            a schedule has a sharp autocorrelation peak; a figure that is
//            merely moving does not.
//   bands    how the variance is spread over frequency.  A sway lives in
//            the 0.15-0.4 Hz band (a two-and-a-half to six-and-a-half
//            second cycle).  A lot of power in that band is the wobble.
//   hold     how much of the run the bone sits inside a degree of where it
//            was half a second ago.
//
// Usage:
//   node scripts/analyze_yxz_motion_texture.mjs <dump.json> [...]
//   node scripts/analyze_yxz_motion_texture.mjs --airi \
//     docs/yxz-audit/series-airi/animation-bare.json

import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

function readSeries(file, bone) {
  const json = JSON.parse(readFileSync(file, 'utf8'))
  const rate = json.rate ?? 10
  const source = json.bones?.[bone]
  if (!source)
    throw new Error(`${file}: no bone ${bone}`)
  return { rate, seconds: json.seconds ?? source.x.length / rate, ...source }
}

function mean(values) {
  return values.reduce((a, b) => a + b, 0) / Math.max(1, values.length)
}

function sd(values) {
  const m = mean(values)
  return Math.sqrt(mean(values.map(v => (v - m) ** 2)))
}

// Autocorrelation of a centred series, normalised so that lag 0 is 1.
function autocorr(values, lag) {
  const m = mean(values)
  const centred = values.map(v => v - m)
  let num = 0
  let den = 0
  for (let i = 0; i + lag < centred.length; i++) {
    num += centred[i] * centred[i + lag]
    den += centred[i] * centred[i]
  }
  return den > 1e-12 ? num / den : 0
}

// The strongest *local* peak of the autocorrelation.
//
// The plain maximum is useless here: any smooth signal is most correlated
// with itself one second later, so the answer is always the shortest lag and
// says nothing.  What matters is whether there is a *secondary* bump -- a
// length the pose comes back around to -- and a bump is a local maximum
// somewhere between one second and a quarter of the run.
function dominantPeriod(values, rate) {
  const minLag = Math.round(rate)
  const maxLag = Math.min(values.length - 2, Math.round(rate * 25))
  let best = { lag: 0, value: -2 }
  for (let lag = minLag; lag <= maxLag; lag++) {
    const value = autocorr(values, lag)
    const before = lag > minLag ? autocorr(values, lag - 1) : -2
    const after = lag < maxLag ? autocorr(values, lag + 1) : -2
    if (value > before && value >= after && value > best.value)
      best = { lag, value }
  }
  return { period: +(best.lag / rate).toFixed(2), peak: +best.value.toFixed(3) }
}

// Variance of a series by frequency band, via a direct DFT at a coarse
// resolution.  The bands are what the eye reads as "slow drift" (below
// 0.05 Hz), "settling" (0.05-0.15 Hz) and "wobbling" (0.15-0.4 Hz).
function bands(values, rate) {
  const n = values.length
  const m = mean(values)
  const centred = values.map(v => v - m)
  const edges = [0, 0.05, 0.15, 0.4, 0.5 * rate]
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

// The share of the run the bone spends inside a tenth of a degree of where
// it was half a second ago.  The eye holds an image for about that long
// before deciding whether it moved.
function holdShare(values, rate) {
  const window = Math.max(1, Math.round(rate * 0.5))
  let held = 0
  let count = 0
  for (let i = window; i < values.length; i++) {
    count++
    if (Math.abs(values[i] - values[i - window]) < 0.1)
      held++
  }
  return Math.round((held / Math.max(1, count)) * 100)
}

function describe(name, values, rate) {
  const period = dominantPeriod(values, rate)
  return {
    name,
    sd: +sd(values).toFixed(2),
    hold: holdShare(values, rate),
    period: period.period,
    peak: period.peak,
    curve: [2, 3, 4, 5, 6, 8, 10, 12, 15, 20].map(seconds =>
      +autocorr(values, Math.round(seconds * rate)).toFixed(2)),
    bands: bands(values, rate),
  }
}

const files = process.argv.slice(2)
if (files.length === 0) {
  console.error('usage: node scripts/analyze_yxz_motion_texture.mjs <dump.json> ...')
  process.exit(1)
}

for (const file of files) {
  const json = JSON.parse(readFileSync(file, 'utf8'))
  const bones = json.bones ? Object.keys(json.bones) : []
  const rate = json.rate ?? 10
  console.log(`\n${basename(file)}   ${json.seconds ?? '?'}s @ ${rate}Hz`)
  console.log('  bone          sd   hold%  period  autocorr   drift<.05  settle .05-.15  wobble .15-.4  fast >.4')
  for (const bone of bones) {
    const source = json.bones[bone]
    const rows = [
      describe('x', source.x, rate),
      describe('y', source.y, rate),
      describe('z', source.z, rate),
    ]
    const mean0 = rows.reduce((a, r) => a + r.sd, 0) / 3
    const meanHold = Math.round(rows.reduce((a, r) => a + r.hold, 0) / 3)
    const bands0 = rows.reduce((a, r) => a + r.bands[0], 0) / 3
    const bands1 = rows.reduce((a, r) => a + r.bands[1], 0) / 3
    const bands2 = rows.reduce((a, r) => a + r.bands[2], 0) / 3
    const bands3 = rows.reduce((a, r) => a + r.bands[3], 0) / 3
    const best = rows.reduce((a, r) => (r.peak > a.peak ? r : a))
    console.log(
      `  ${bone.padEnd(12)} ${mean0.toFixed(2).padStart(5)} ${String(meanHold).padStart(6)}`
      + ` ${String(best.period).padStart(7)} ${String(best.peak).padStart(9)}`
      + ` ${bands0.toFixed(3).padStart(12)} ${bands1.toFixed(3).padStart(14)}`
      + ` ${bands2.toFixed(3).padStart(14)} ${bands3.toFixed(3).padStart(10)}`,
    )
    console.log(
      `  ${''.padEnd(12)} autocorr @ 2/3/4/5/6/8/10/12/15/20s:`
      + rows[0].curve.map(v => String(v).padStart(6)).join(''),
    )
  }
}
