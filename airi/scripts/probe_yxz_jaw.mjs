/**
 * What is the rough band under the chin made of?
 *
 * Between the helmet's lower rim and the neck there is a dark, noisy strip.
 * Three things could produce it and they need different fixes:
 *
 *   texture     the Tripo base colour atlas is auto-generated and bakes the
 *               scan's interior into small dark islands, so the band could
 *               simply be painted noise
 *   z-fighting  two nearly coincident surfaces -- the shell and the liner
 *               under it -- fighting for the depth buffer
 *   geometry    a genuine hole in the scan, with the inside of the head
 *               visible through it
 *
 * The variants below each rule one out: with the texture gone the band can
 * only be geometry or depth, and with a polygon offset a depth fight would
 * collapse into a clean surface.
 *
 * Usage: node scripts/probe_yxz_jaw.mjs [baseUrl] [outDir]
 */

import { mkdir } from 'node:fs/promises'
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
const outDir = process.argv[3] ?? 'docs/yxz-jaw'
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')

await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    const { width, height } = await sharp(file).metadata()
    await sharp(file)
      .extract({
        left: Math.round(width * 0.32),
        top: Math.round(height * 0.4),
        width: Math.round(width * 0.32),
        height: Math.round(height * 0.14),
      })
      .resize({ width: 960, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-jaw.png`))
  }
  console.log('SHOT', name)
}

await shoot('1-as-is')

// No texture at all: whatever is left is geometry or depth.
await page.evaluate(() => {
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list)
      material.map = null
  })
})
await page.waitForTimeout(4000)
await shoot('2-no-texture')

// Back to the texture, but with a polygon offset so coincident surfaces stop
// fighting for the depth buffer.
await page.reload({ waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      material.polygonOffset = true
      material.polygonOffsetFactor = 1
      material.polygonOffsetUnits = 1
      material.needsUpdate = true
    }
  })
})
await page.waitForTimeout(6000)
await shoot('3-polygon-offset')

// Last suspect: the band is a surface that shadows itself, and on a sheet
// seen edge-on the shadow map lands on it in a speckle.
await page.reload({ waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  window.__yxzDebug?.scene?.()?.traverse((object) => {
    if (object.isDirectionalLight)
      object.castShadow = false
  })
})
await page.waitForTimeout(6000)
await shoot('4-no-shadow')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
