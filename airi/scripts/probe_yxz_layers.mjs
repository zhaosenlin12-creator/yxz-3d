/**
 * Separate the three things that can draw a line across the character.
 *
 * A pale slash across the chin and a blue diagonal on the wing look like
 * scratches, but there are three very different things that can produce
 * one, and they need three different fixes:
 *
 *   albedo    the line is painted in the base colour atlas -- the fix is
 *             in the texture, and no amount of geometry work will touch it
 *   shape     the line is a real sheet of geometry standing off the body
 *             or a gap between two sheets -- the fix is to weld, thicken
 *             or delete the sheet
 *   normal    the line is where two triangles disagree about which way
 *             they face -- the fix is in the normals
 *
 * So the model is photographed three times: once with the base colour
 * and no lighting at all, once as flat unlit geometry, and once with
 * the surface normals as colour.  Whatever survives the flat unlit
 * pass is geometry; whatever only shows up under the normals pass is
 * a shading problem; whatever is in the albedo pass is painted.
 *
 * Usage: node scripts/probe_yxz_layers.mjs [baseUrl] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
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
const outDir = process.argv[3] ?? 'docs/yxz-layers'
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 })

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
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/**
 * The four places a defect has to be read off.  The crop is a fraction of
 * the canvas so the box survives a viewport change, and it is blown up
 * afterwards so a one-pixel line is not a one-pixel line.
 */
const CROPS = {
  head: { x: 0.28, y: 0.06, w: 0.44, h: 0.44 },
  chin: { x: 0.36, y: 0.34, w: 0.30, h: 0.16 },
  wing: { x: 0.48, y: 0.46, w: 0.32, h: 0.24 },
  halo: { x: 0.28, y: 0.0, w: 0.44, h: 0.26 },
}

async function cropRegions(file, tag) {
  if (!sharp)
    return
  const { width, height } = await sharp(file).metadata()
  for (const [name, box] of Object.entries(CROPS)) {
    await sharp(file)
      .extract({
        left: Math.round(box.x * width),
        top: Math.round(box.y * height),
        width: Math.round(box.w * width),
        height: Math.round(box.h * height),
      })
      .resize({ width: 1000, kernel: 'nearest' })
      .toFile(path.join(outDir, `${tag}-${name}.png`))
  }
}

async function shoot(tag) {
  const file = path.join(outDir, `${tag}.png`)
  await canvas.screenshot({ path: file })
  await cropRegions(file, tag)
  console.log('SHOT', tag)
}

/**
 * Swap every material for one flat substitute.
 *
 * `mode` is one of:
 *   albedo  the base colour with no lighting -- what the texture says
 *   shape   flat unlit colour -- the silhouette and nothing else
 *   normal  the surface normal as colour -- where the shading breaks
 */
async function swap(mode) {
  await page.evaluate((mode) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    if (!three || !scene)
      return
    const renderer = window.__yxzDebug?.renderer?.()
    if (renderer) {
      renderer.toneMapping = three.NoToneMapping
      renderer.outputColorSpace = three.LinearSRGBColorSpace
    }
    window.__yxzDebug?.outlinePass?.() && (window.__yxzDebug.outlinePass().enabled = false)

    // The original materials are kept so the albedo pass can borrow the
    // base colour map from them.
    window.__yxzOriginalMaterials ??= []
    let index = 0
    scene.traverse((object) => {
      if (!object.isMesh)
        return
      if (!window.__yxzOriginalMaterials[index])
        window.__yxzOriginalMaterials[index] = object.material
      const original = window.__yxzOriginalMaterials[index]
      const single = Array.isArray(original) ? original[0] : original
      index += 1

      if (mode === 'albedo') {
        const material = new three.MeshBasicMaterial({
          map: single?.map ?? null,
          transparent: true,
          side: three.FrontSide,
        })
        object.material = material
        return
      }
      if (mode === 'shape') {
        // Flat mid grey with no lighting: a sheet standing off the body
        // shows as a step in the silhouette, and a gap between two sheets
        // shows as a hole in it.
        object.material = new three.MeshBasicMaterial({
          color: 0x9A9A9A,
          side: three.DoubleSide,
          transparent: true,
        })
        return
      }
      object.material = new three.MeshNormalMaterial({
        side: three.DoubleSide,
        transparent: true,
      })
    })
  }, mode)
  await page.waitForTimeout(2500)
}

await shoot('0-mtoon')
await swap('albedo')
await shoot('1-albedo')
await swap('shape')
await shoot('2-shape')
await swap('normal')
await shoot('3-normal')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
