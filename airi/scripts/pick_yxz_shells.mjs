/**
 * Which shell is that speck over there?
 *
 * The false colour render and the textured render are the same picture
 * from the same camera, so a pixel in one is the same pixel in the
 * other.  This reads a rectangle of the picture and names the shell
 * under every pixel of it, and says how much of the rectangle each
 * shell covers and where in the rectangle it sits.
 *
 * A region is given as x0,y0,x1,y1 in pixels, with the origin at the
 * top left.  Several regions can be given at once; each is reported on
 * its own.
 *
 * Usage: node scripts/pick_yxz_shells.mjs <ids.json> <ids-ids.png> \
 *   <ids-textured.png> <region> [region ...]
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

const [idsJson, idsPng, texturedPng, ...regions] = process.argv.slice(2)
const meta = JSON.parse(readFileSync(idsJson, 'utf8'))
const sharp = await importSharp()

const ids = await sharp(idsPng).raw().toBuffer({ resolveWithObject: true })
const textured = await sharp(texturedPng).raw().toBuffer({ resolveWithObject: true })
const { width, height, channels } = ids.info

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

for (const region of regions) {
  const [x0, y0, x1, y1] = region.split(',').map(Number)
  const counts = new Map()
  for (let y = Math.max(0, y0); y < Math.min(height, y1); y++) {
    for (let x = Math.max(0, x0); x < Math.min(width, x1); x++) {
      const at = (y * width + x) * channels
      const key = [0, 1, 2].map(i => ids.data[at + i]).join(',')
      if (key === bodyKey)
        continue
      const id = byColour.get(key)
      if (id === undefined)
        continue
      const t = (y * width + x) * textured.info.channels
      const lum = 0.2126 * textured.data[t] + 0.7152 * textured.data[t + 1] + 0.0722 * textured.data[t + 2]
      const record = counts.get(id) ?? { pixels: 0, lum: 0, bx0: x, by0: y, bx1: x, by1: y }
      record.pixels += 1
      record.lum += lum
      record.bx0 = Math.min(record.bx0, x)
      record.by0 = Math.min(record.by0, y)
      record.bx1 = Math.max(record.bx1, x)
      record.by1 = Math.max(record.by1, y)
      counts.set(id, record)
    }
  }
  const rows = [...counts.entries()]
    .map(([id, record]) => ({ id, ...record }))
    .sort((a, b) => b.pixels - a.pixels)
  console.log(`REGION ${region}  (${rows.length} shells)`)
  for (const row of rows) {
    const info = meta.info?.[row.id] ?? {}
    const mean = Math.round((row.lum / row.pixels) * 10) / 10
    console.log(
      `  shell ${row.id} pixels=${row.pixels} meanLum=${mean}`
      + ` box=[${row.bx0},${row.by0}]..[${row.bx1},${row.by1}]`
      + ` faces=${info.faces} z=[${info.zMin},${info.zMax}]`
      + ` uv=[${info.uvLow?.[0]},${info.uvLow?.[1]}]..[${info.uvHigh?.[0]},${info.uvHigh?.[1]}]`,
    )
  }
}
