/**
 * Which shell is the confetti?
 *
 * The false colour render gives every shell a colour of its own, and the
 * textured render shows what the shell actually looks like.  The two are
 * the same picture from the same camera, so a pixel in one is the same
 * pixel in the other: reading the colour in the first and the paint in
 * the second names the shell.
 *
 * The shell is reported for every pixel of a region, together with how
 * many pixels it covers, so a shell that is a few stray triangles and a
 * shell that is the whole helmet are told apart by their size.
 *
 * Usage: node scripts/join_yxz_island_ids.mjs <ids.json> <ids-ids.png> \
 *   <ids-textured.png> [rowTop] [rowBottom]
 */

import { readFileSync } from 'node:fs'
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
  const { readdirSync } = await import('node:fs')
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).filter(e => e.startsWith('sharp@')).sort().at(-1)
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  return (await import(pathToFileURL(entry).href)).default
}

const [idsJson, idsPng, texturedPng, rowTopArg, rowBottomArg] = process.argv.slice(2)
const meta = JSON.parse(readFileSync(idsJson, 'utf8'))
const sharp = await importSharp()

const ids = await sharp(idsPng).raw().toBuffer({ resolveWithObject: true })
const textured = await sharp(texturedPng).raw().toBuffer({ resolveWithObject: true })
const { width, height, channels } = ids.info

// The colour of every shell, as it was drawn, keyed by its own shade.
// The colour goes in as a linear value and comes out of the file
// sRGB encoded, so it has to be encoded here too or nothing will match.
function toSrgb(value) {
  return value <= 0.0031308
    ? value * 12.92
    : 1.055 * Math.pow(value, 1 / 2.4) - 0.055
}

const byColour = new Map()
for (const [id, colour] of Object.entries(meta.colours)) {
  const key = [0, 1, 2]
    .map(i => Math.round(toSrgb(colour[i]) * 255))
    .join(',')
  byColour.set(key, Number(id))
}
const bodyKey = '255,0,255'

const rowTop = Number(rowTopArg ?? 0)
const rowBottom = Number(rowBottomArg ?? height)

const counts = new Map()
for (let y = rowTop; y < rowBottom; y++) {
  for (let x = 0; x < width; x++) {
    const at = (y * width + x) * channels
    const key = [0, 1, 2].map(i => ids.data[at + i]).join(',')
    if (key === bodyKey)
      continue
    const id = byColour.get(key)
    if (id === undefined)
      continue
    const t = (y * width + x) * textured.info.channels
    const lum = 0.2126 * textured.data[t] + 0.7152 * textured.data[t + 1] + 0.0722 * textured.data[t + 2]
    const record = counts.get(id) ?? { pixels: 0, lum: 0 }
    record.pixels += 1
    record.lum += lum
    counts.set(id, record)
  }
}

const rows = [...counts.entries()]
  .map(([id, record]) => ({
    id,
    pixels: record.pixels,
    meanLum: Math.round((record.lum / record.pixels) * 10) / 10,
  }))
  .sort((a, b) => b.pixels - a.pixels)

console.log(`JOIN_ROWS ${rowTop}..${rowBottom}`)
for (const row of rows) {
  const info = meta.info?.[row.id] ?? {}
  console.log(
    `JOIN_SHELL ${row.id} pixels=${row.pixels} meanLum=${row.meanLum}`
    + ` faces=${info.faces} zMin=${info.zMin} zMax=${info.zMax}`
    + ` uv=[${info.uvLow?.[0]},${info.uvLow?.[1]}]..[${info.uvHigh?.[0]},${info.uvHigh?.[1]}]`,
  )
}

