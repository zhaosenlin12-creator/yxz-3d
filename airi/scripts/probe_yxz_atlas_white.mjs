/**
 * Find the stray white strokes in the base-colour atlas.
 *
 * A handful of the lines that read as "scratches" on the character are
 * painted into the atlas rather than modelled, and they are easy to
 * miss: the body is a very light blue-grey, and a stroke a shade
 * lighter than the body only shows up once the light hits it.  Here
 * they are found the only reliable way -- by their colour, which is
 * pure white where the body around them is not.
 *
 * The strokes are thin, so each one is reported with its shape: a
 * scratch is long and thin, a genuine white detail such as an eye
 * glint is round and small.  That difference is what tells the repair
 * pass which white it may take and which white it has to keep.
 *
 * Usage: node scripts/probe_yxz_atlas_white.mjs [atlasPng] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
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

const atlas = process.argv[2]
  ?? 'docs/yxz-atlas/source-0-Color_886880fc-6cae-4d94-9577-31f0c6026a55.png'
const outDir = process.argv[3] ?? 'docs/yxz-atlas/white'
await mkdirSync(outDir, { recursive: true })

const sharp = await importSharp()
if (!sharp)
  throw new Error('sharp is not available')

const { data, info } = await sharp(atlas).raw().toBuffer({ resolveWithObject: true })
const { width, height, channels } = info

// Pure white, or within a hair of it, and neutral so the cyan and blue
// accents are not caught.
const white = new Uint8Array(width * height)
for (let i = 0; i < width * height; i++) {
  const p = i * channels
  const r = data[p]
  const g = data[p + 1]
  const b = data[p + 2]
  if (r >= 246 && g >= 246 && b >= 246 && Math.max(r, g, b) - Math.min(r, g, b) <= 10)
    white[i] = 1
}

const seen = new Uint8Array(width * height)
const components = []
for (let i = 0; i < white.length; i++) {
  if (!white[i] || seen[i])
    continue
  const stack = [i]
  seen[i] = 1
  const members = []
  let minX = width
  let maxX = 0
  let minY = height
  let maxY = 0
  while (stack.length) {
    const at = stack.pop()
    members.push(at)
    const x = at % width
    const y = (at / width) | 0
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const nx = x + dx
      const ny = y + dy
      if (nx < 0 || ny < 0 || nx >= width || ny >= height)
        continue
      const n = ny * width + nx
      if (white[n] && !seen[n]) {
        seen[n] = 1
        stack.push(n)
      }
    }
  }
  const boxWidth = maxX - minX + 1
  const boxHeight = maxY - minY + 1
  const area = members.length
  const longest = Math.max(boxWidth, boxHeight)
  components.push({
    area,
    box: [minX, minY, boxWidth, boxHeight],
    fill: area / (boxWidth * boxHeight),
    longest,
  })
}

components.sort((a, b) => b.area - a.area)
const strokes = components.filter(c => c.longest >= 24 && c.fill < 0.34)

console.log('ATLAS', JSON.stringify({ width, height, components: components.length }))
console.log('STROKES', strokes.length)
for (const stroke of strokes.slice(0, 40))
  console.log('STROKE', JSON.stringify(stroke))

// A contact sheet of the strokes, so each one can be looked at without
// hunting through a four-thousand-pixel atlas.
for (const [index, stroke] of strokes.slice(0, 12).entries()) {
  const [x, y, w, h] = stroke.box
  const pad = 24
  const left = Math.max(0, x - pad)
  const top = Math.max(0, y - pad)
  await sharp(atlas)
    .extract({
      left,
      top,
      width: Math.min(width - left, w + pad * 2),
      height: Math.min(height - top, h + pad * 2),
    })
    .resize({ width: 700, kernel: 'nearest' })
    .toFile(path.join(outDir, `stroke-${index}.png`))
}
console.log('OUT', outDir)
