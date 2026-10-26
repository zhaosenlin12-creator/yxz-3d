/**
 * Find the places the character's shell is open, by reading the alpha of
 * the picture rather than by looking at it.
 *
 * The renderer is created with an alpha channel and nothing ever writes an
 * opaque background into it, so a pixel of the model is opaque and a pixel
 * of nowhere is not.  A single sided material over an open shell therefore
 * does not draw a bright patch -- it draws nothing at all, and the hole is
 * invisible in a screenshot and obvious in the alpha.
 *
 * That is the only way to tell the two apart.  A hole and a panel of very
 * pale paint are the same colour on a pale stage, and they need opposite
 * repairs: one needs geometry grown over it, the other needs nothing.
 *
 * The holes are found by flooding the transparent pixels and reporting the
 * groups that sit inside the silhouette.  The gap between two limbs and
 * the middle of the halo are transparent too and are not faults, so the
 * groups are reported by size and position rather than as a total.
 *
 * Usage: node scripts/probe_yxz_holes.mjs [baseUrl] [outDir]
 */

import { mkdir, writeFile } from 'node:fs/promises'
import { existsSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).filter(e => e.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

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

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(e => e.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-holes'
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1040, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  // The canvas draws nothing where the model is not, so the page shows
  // through every hole.  Painting the page a colour that appears nowhere
  // in the character turns each hole into a magenta patch that can be
  // counted, and a screenshot keeps no alpha to read it from.
  document.documentElement.style.setProperty('background', '#ff00ff', 'important')
  document.body.style.setProperty('background', '#ff00ff', 'important')
  document.body.style.setProperty('opacity', '1', 'important')
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const box = await page.locator('.yxz-real-model-canvas canvas').boundingBox()
const buffer = await page.screenshot({
  omitBackground: true,
  clip: { x: box.x, y: box.y, width: box.width, height: box.height },
})
const file = path.join(outDir, 'alpha.png')
await writeFile(file, buffer)
console.log('SHOT', file, 'errors=', JSON.stringify(errors))

const { data, info } = await sharp(buffer).raw().toBuffer({ resolveWithObject: true })
const { width, height, channels } = info
console.log('SIZE', width, height, 'channels', channels)

const clear = new Uint8Array(width * height)
for (let index = 0; index < width * height; index++) {
  const offset = index * channels
  const magenta = data[offset] > 200 && data[offset + 1] < 90 && data[offset + 2] > 200
  if (magenta)
    clear[index] = 1
}

// A hole is transparent *inside* the silhouette, so the transparent
// pixels are flood filled and the groups that touch the edge of the
// picture -- the background, the gap between the legs, the middle of the
// halo -- are left out by distance rather than by judgement.
const seen = new Uint8Array(width * height)
const groups = []
const stack = []
for (let start = 0; start < width * height; start++) {
  if (!clear[start] || seen[start])
    continue
  seen[start] = 1
  stack.push(start)
  let pixels = 0
  let minX = width
  let maxX = 0
  let minY = height
  let maxY = 0
  let touchesEdge = false
  while (stack.length > 0) {
    const index = stack.pop()
    const x = index % width
    const y = (index - x) / width
    pixels++
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
    if (x === 0 || y === 0 || x === width - 1 || y === height - 1)
      touchesEdge = true
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx
        const ny = y + dy
        if (nx < 0 || ny < 0 || nx >= width || ny >= height)
          continue
        const neighbour = ny * width + nx
        if (clear[neighbour] && !seen[neighbour]) {
          seen[neighbour] = 1
          stack.push(neighbour)
        }
      }
    }
  }
  if (pixels >= 25)
    groups.push({ pixels, box: [minX, minY, maxX, maxY], background: touchesEdge })
}

groups.sort((a, b) => b.pixels - a.pixels)
console.log('GROUPS', JSON.stringify(groups.slice(0, 30)))
console.log('INTERIOR', JSON.stringify(groups.filter(group => !group.background)))
await browser.close()
