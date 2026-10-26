/**
 * Which part of the render stack is making the character look shattered?
 *
 * The black speckle on the head is not in the base colour atlas, so it is
 * made at draw time.  This switches one thing at a time -- shadows off,
 * outline off, double sided -- and crops the same region of the head each
 * time, so the culprit is the switch that makes the speckle go away.
 *
 * Usage: node scripts/ab_yxz_look.mjs [baseUrl] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
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
  const exe = path.join(root, revision, 'chrome-win64', 'chrome.exe')
  return existsSync(exe) ? exe : undefined
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-diag/ab'
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.waitForTimeout(3000)

// The head occupies the upper middle of the canvas.  Crop there so the
// speckle is the subject rather than a detail.
const clip = { x: 430, y: 130, width: 520, height: 400 }

async function shot(name) {
  const file = path.join(outDir, `${name}.png`)
  await page.screenshot({ path: file, clip })
  console.log(`AB_SHOT ${file}`)
}

await shot('a-base')

await page.evaluate(() => {
  const debug = window.__yxzDebug
  debug.renderer().shadowMap.enabled = false
  debug.scene().traverse((object) => {
    if (object.material)
      object.material.needsUpdate = true
  })
})
await page.waitForTimeout(900)
await shot('b-noshadow')

await page.evaluate(() => {
  const debug = window.__yxzDebug
  debug.renderer().shadowMap.enabled = true
  debug.outlinePass().enabled = false
})
await page.waitForTimeout(900)
await shot('c-nooutline')

await page.evaluate(() => {
  const debug = window.__yxzDebug
  debug.setSide(debug.three.DoubleSide)
})
await page.waitForTimeout(900)
await shot('d-doubleside')

// Full page, so the limbs can be judged as well as the head.
await page.evaluate(() => {
  const debug = window.__yxzDebug
  debug.setSide(debug.three.FrontSide)
  debug.outlinePass().enabled = true
})
await page.waitForTimeout(900)
const full = path.join(outDir, 'e-full.png')
await page.screenshot({ path: full })
console.log(`AB_SHOT ${full}`)

// How much of the head is dark?  A number is easier to compare between
// runs than an eyeball, and it is the number that has to go down.
if (sharp) {
  for (const name of ['a-base', 'b-noshadow', 'c-nooutline', 'd-doubleside']) {
    const file = path.join(outDir, `${name}.png`)
    const { data, info } = await sharp(file).raw().toBuffer({ resolveWithObject: true })
    let dark = 0
    let total = 0
    for (let i = 0; i < data.length; i += info.channels) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const l = 0.2126 * r + 0.7152 * g + 0.0722 * b
      if (l < 90)
        dark += 1
      total += 1
    }
    console.log(`AB_DARK ${name} ${(dark / total * 100).toFixed(2)}%`)
  }
}

console.log(`AB_ERRORS ${JSON.stringify(errors)}`)
await browser.close()
