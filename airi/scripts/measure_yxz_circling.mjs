/** How much the head's pose draws a closed shape.
 *
 * "Circling" is the complaint that has been reported against this model
 * more than once, and it is a specific thing: a head whose pose comes
 * back to where it has been before, on a cycle, so that the eye can
 * trace the closed shape it is describing.
 *
 * The number here is that shape, measured.  The head's pose is taken as
 * a point in the plane of its two most visible axes, and every time it
 * comes back within a small distance of a point it visited at least a
 * few seconds earlier, that is one return.  A figure that is looking
 * around has few returns; a figure that is circling has many.
 *
 * The reference character is measured on the same scale, because she is
 * the thing the motion is being compared against and she is a loop, so
 * she has returns by construction -- the number is not zero and never
 * will be.  What matters is the head's *pose* returning, which is a
 * different thing from its motion returning.
 *
 * Usage:
 *   node scripts/measure_yxz_circling.mjs <series.json> [series.json ...]
 */

import { readFileSync } from 'node:fs'

const files = process.argv.slice(2)
if (files.length === 0) {
  console.error('usage: node scripts/measure_yxz_circling.mjs <series.json> ...')
  process.exit(1)
}

const TOLERANCE = 0.6
const MIN_GAP = 4

for (const file of files) {
  const data = JSON.parse(readFileSync(file, 'utf8'))
  const bone = data.bones?.head
  if (!bone) {
    console.log(`${file}: no head in the series`)
    continue
  }
  const pitch = bone.x
  const roll = bone.z
  const rate = data.rate ?? 10
  const points = pitch.map((value, index) => [value, roll[index]])

  let returns = 0
  let path = 0
  let area = 0
  for (let i = 1; i < points.length; i++) {
    path += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
    area += points[i][0] * points[i - 1][1] - points[i - 1][0] * points[i][1]
    // A return is a pose the head has been in before, after a long
    // enough gap that it could not be the same movement still going.
    const minGap = Math.round(MIN_GAP * rate)
    for (let j = 0; j < i - minGap; j += 5) {
      if (Math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1]) < TOLERANCE) {
        returns++
        break
      }
    }
  }
  const seconds = points.length / rate
  const span = points.reduce(
    (acc, [p, r]) => ({
      p: Math.min(acc.p, p),
      P: Math.max(acc.P, p),
      r: Math.min(acc.r, r),
      R: Math.max(acc.R, r),
    }),
    { p: Infinity, P: -Infinity, r: Infinity, R: -Infinity },
  )
  const box = (span.P - span.p) * (span.R - span.r)
  console.log(`${file}`)
  console.log(`  seconds ${seconds.toFixed(0)}  pose returns ${returns}`
    + ` (${(returns / seconds).toFixed(2)}/s)   path ${(path / seconds).toFixed(2)} deg/s`)
  console.log(`  pitch span ${(span.P - span.p).toFixed(2)}  roll span ${(span.R - span.r).toFixed(2)}`
    + `  box ${box.toFixed(1)}  path/box ${(path / Math.max(box, 0.01)).toFixed(2)}`)
}
