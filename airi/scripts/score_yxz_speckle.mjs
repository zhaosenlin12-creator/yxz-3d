/**
 * Score how speckled each face crop is, so the cause can be named by number
 * rather than by eye.
 *
 * The speckle on the visor is a band of pixels that flip between two
 * neighbouring shades, so it shows up as local high-frequency noise.  The
 * score is the mean absolute difference between each pixel and the median
 * of its 3x3 neighbourhood: a smooth gradient scores near zero, a speckled
 * band scores high, and the number is comparable between crops.
 *
 * Usage: node scripts/score_yxz_speckle.mjs <dir>
 */

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

async function importSharp() {
  const require = createRequire(import.meta.url)
  try {
    return require('sharp')
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).filter(e => e.startsWith('sharp@')).sort().at(-1)
  if (!match)
    return null
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  if (!existsSync(entry))
    return null
  return (await import(pathToFileURL(entry).href)).default
}

const dir = process.argv[2] ?? 'docs/yxz-speckle'
const sharp = await importSharp()
if (!sharp)
  throw new Error('sharp not found')

const files = readdirSync(dir).filter(f => f.endsWith('-face.png')).sort()

for (const file of files) {
  const { data, info } = await sharp(path.join(dir, file))
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true })
  const { width, height } = info
  const at = (x, y) => data[y * width + x]

  let sum = 0
  let count = 0
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const window = [
        at(x - 1, y - 1), at(x, y - 1), at(x + 1, y - 1),
        at(x - 1, y), at(x, y), at(x + 1, y),
        at(x - 1, y + 1), at(x, y + 1), at(x + 1, y + 1),
      ].sort((a, b) => a - b)
      const median = window[4]
      sum += Math.abs(at(x, y) - median)
      count++
    }
  }
  console.log(`${file.padEnd(34)} speckle=${(sum / count).toFixed(3)}`)
}
