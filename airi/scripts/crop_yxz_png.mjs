/**
 * A close look at part of a capture.
 *
 * The whole-figure captures answer "does it read as solid"; they cannot
 * answer "what is that line across the cheek".  This crops a region out
 * of a capture so it can be looked at on its own terms.
 *
 * Usage: node scripts/crop_yxz_png.mjs <in.png> <out.png> <x> <y> <w> <h> [scale]
 */

import { existsSync, readdirSync } from 'node:fs'
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
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  if (!existsSync(entry))
    return null
  return (await import(pathToFileURL(entry).href)).default
}

const [input, output, x, y, w, h, scale] = process.argv.slice(2)
const sharp = await importSharp()
await sharp(input)
  .extract({ left: Number(x), top: Number(y), width: Number(w), height: Number(h) })
  .resize(Number(scale ?? 1) * Number(w))
  .png()
  .toFile(output)
console.log(`CROP ${output}`)

