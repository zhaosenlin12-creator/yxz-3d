/**
 * Sweep the cel terminator.
 *
 * MToon shades a surface with
 *
 *     linearstep(-1 + toony, 1 - toony, dotNL + shift)
 *
 * so `shadingToonyFactor` decides how wide the ramp between the lit tone
 * and the shade tone is.  A low value spreads the ramp over most of the
 * sphere, the light never reaches full white anywhere, and the character
 * reads as a soft grey lump: that is the plastic look.  A high value
 * narrows the ramp to a couple of degrees and the character reads as a
 * cel: a lit shape, a shade shape, and a clean line between them.
 *
 * The loader pulls the factor towards 1 before it reaches the shader
 * (`lerp(toony, 1, 0.5 + 0.5 * shift)`), so the value written into the
 * asset is not the value that ends up shading it.  The sweep therefore
 * measures what the screen shows, not what the file says.
 *
 * Usage: node scripts/sweep_yxz_toony.mjs [baseUrl] [outDir]
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
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-toony'
await mkdirSync(outDir, { recursive: true })

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

const looks = [
  { name: '1-toony-022-current', toony: 0.22, shift: 0, key: 2.3, exposure: 0.95, shade: [0.33, 0.40, 0.60] },
  { name: '2-toony-06', toony: 0.6, shift: 0, key: 2.3, exposure: 0.95, shade: [0.33, 0.40, 0.60] },
  { name: '3-toony-08', toony: 0.8, shift: 0, key: 2.3, exposure: 0.95, shade: [0.33, 0.40, 0.60] },
  { name: '4-toony-09', toony: 0.9, shift: 0, key: 2.3, exposure: 0.95, shade: [0.33, 0.40, 0.60] },
  { name: '5-toony-09-softkey', toony: 0.9, shift: 0, key: 1.7, exposure: 0.95, shade: [0.33, 0.40, 0.60] },
  { name: '6-toony-09-paleshade', toony: 0.9, shift: 0, key: 1.9, exposure: 0.95, shade: [0.52, 0.56, 0.68] },
  { name: '7-toony-09-shift', toony: 0.9, shift: -0.12, key: 1.9, exposure: 0.95, shade: [0.46, 0.50, 0.64] },
  { name: '8-toony-09-lowerkey', toony: 0.9, shift: 0, key: 1.5, exposure: 1.0, shade: [0.40, 0.45, 0.64] },
]

async function apply(look) {
  await page.evaluate((look) => {
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const renderer = window.__yxzDebug?.renderer?.()
    scene.traverse((object) => {
      if (object.isDirectionalLight && object.intensity > 1)
        object.intensity = look.key
      if (!object.isMesh)
        return
      const material = object.material
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        m.shadingToonyFactor = look.toony
        m.shadingShiftFactor = look.shift
        m.shadeColorFactor?.setRGB(...look.shade)
      }
    })
    if (renderer)
      renderer.toneMappingExposure = look.exposure
  }, look)
  await page.waitForTimeout(2500)
}

for (const look of looks) {
  await apply(look)
  const file = path.join(outDir, `${look.name}.png`)
  await canvas.screenshot({ path: file })
  console.log('SHOT', look.name)
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
