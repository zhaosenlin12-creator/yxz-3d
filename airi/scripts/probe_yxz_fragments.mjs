/**
 * Tell the "broken up" look apart into geometry versus shading.
 *
 * Three separate things read as fragmentation on this character, and they
 * need different fixes, so they get separated here in one browser session
 * instead of one capture per hypothesis:
 *
 *   as-is        what the stage actually shows
 *   silhouette   the whole scene forced to flat black, which turns any sheet
 *                that intersects or protrudes into a plainly visible flange --
 *                this is the test for "is that white smear real geometry"
 *   mask         the same flat pass painted white on black, which is the
 *                silhouette the outline should be derived from
 *
 * Note this deliberately goes through `scene.overrideMaterial` rather than
 * poking MToon uniforms: three-vrm re-applies the VRM extension to every
 * material from `material.update()` each frame, so a uniform written from the
 * console is reverted before the next draw and the variant silently renders
 * the unmodified model.
 *
 * Usage: node scripts/probe_yxz_fragments.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-fragments'
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/**
 * The three places the "broken up" look is most obvious, as fractions of
 * the canvas so the box survives a viewport change.  A crop that is too
 * wide shows the whole body and the defect is a couple of pixels; a crop
 * that is too tight hides what the defect is attached to.
 */
const CROPS = {
  head: { x: 0.28, y: 0.08, w: 0.44, h: 0.42 },
  chin: { x: 0.38, y: 0.36, w: 0.28, h: 0.16 },
  shoulder: { x: 0.50, y: 0.46, w: 0.30, h: 0.22 },
  halo: { x: 0.30, y: 0.02, w: 0.40, h: 0.24 },
}

/**
 * Blow one region of a shot up so a one-pixel defect is visible, and do it
 * for the flat pass as well, so the same defect can be compared between
 * the shaded image and the silhouette.
 */
async function cropRegions(file, tag) {
  if (!sharp)
    return
  const { width, height } = await sharp(file).metadata()
  for (const [name, box] of Object.entries(CROPS)) {
    const left = Math.round(box.x * width)
    const top = Math.round(box.y * height)
    await sharp(file)
      .extract({
        left,
        top,
        width: Math.round(box.w * width),
        height: Math.round(box.h * height),
      })
      .resize({ width: 1000, kernel: 'nearest' })
      .toFile(path.join(outDir, `${tag}-${name}.png`))
  }
}

async function park() {
  await page.evaluate(() => {
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  await page.waitForTimeout(2500)
}

await park()
await canvas.screenshot({ path: `${outDir}/1-as-is.png` })
await cropRegions(`${outDir}/1-as-is.png`, '1-as-is')

// Flat black: anything that reads as a flange here is real geometry sticking
// through the outer skin, not a highlight.
await page.evaluate(() => {
  const three = window.__yxzVrm.scene.constructor
  void three
  const scene = window.__yxzVrm.scene
  scene.overrideMaterial = new (Object.getPrototypeOf(scene).constructor === Object
    ? Object
    : window.__THREE_MESH_BASIC__ || Object)()
})
await page.evaluate(() => {
  // The component keeps a reference to three in module scope, so build the
  // material from an existing one instead of importing three again.
  let basic = null
  window.__yxzVrm.scene.traverse((object) => {
    if (basic || !object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      if (material && material.isMeshBasicMaterial) {
        basic = material
        break
      }
    }
  })
  window.__yxzFlatMaterial = basic ?? null
})
await page.evaluate(() => {
  const scene = window.__yxzVrm.scene
  const material = window.__yxzFlatMaterial
  if (material) {
    material.color.setRGB(0, 0, 0)
    material.transparent = false
    scene.overrideMaterial = material
  }
  else {
    scene.overrideMaterial = null
  }
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/2-silhouette-black.png` })
await cropRegions(`${outDir}/2-silhouette-black.png`, '2-silhouette-black')

await page.evaluate(() => {
  const material = window.__yxzFlatMaterial
  if (material)
    material.color.setRGB(1, 1, 1)
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/3-mask-white.png` })
await cropRegions(`${outDir}/3-mask-white.png`, '3-mask-white')

console.log('OUT', outDir)
await browser.close()
