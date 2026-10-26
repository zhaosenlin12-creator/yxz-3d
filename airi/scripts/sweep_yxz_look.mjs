/**
 * Sweep the lighting and the MToon settings against a fixed list of looks.
 *
 * The character is a nearly white shell standing on a nearly white page.
 * That is the whole plastic problem in one sentence: with a white key
 * light, a white body and a white ground there is nothing for the eye to
 * read, so the model reads as a white toy no matter how good the geometry
 * is.  The fix is not more light, it is light with a direction and a
 * temperature: a warm key on the lit side, a cool bounce on the shadow
 * side, and a rim that separates the silhouette from the page.
 *
 * Every look in the sweep sets the whole scene, so the shots stay
 * comparable and a difference between two of them is always the one thing
 * that moved.
 *
 * Usage: node scripts/sweep_yxz_look.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-look-sweep'
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

/**
 * The lighting rig the scene builds, and the MToon parameters on top of it.
 * `null` for a field means "leave it alone".
 */
const looks = [
  {
    name: '1-current',
    toony: 0.22,
    shift: 0,
    bounce: null,
    hemi: [0xEBF9FF, 0x18314B, 0.16],
    key: { color: 0xFFFFFF, intensity: 2.3, position: [3, 5, 5] },
    fill: { color: 0xBBD9FF, intensity: 0.14, position: [-4, 2.5, 3] },
    rim: { color: 0x16C9FF, intensity: 1.15, position: [-3, 2.7, 2.5] },
    exposure: 0.95,
    mtoon: { shade: [0.33, 0.40, 0.60], toony: 0.22, rimMultiply: null, rimMix: 0.55, paramRim: [0.55, 0.70, 0.92], fresnel: 2.6, lift: 0 },
  },
  {
    name: '2-warm-key',
    toony: 0.9,
    shift: 0,
    bounce: null,
    hemi: [0xEAF3FF, 0x2A3A55, 0.30],
    key: { color: 0xFFF1DE, intensity: 2.1, position: [3, 5, 5] },
    fill: { color: 0xA9C9FF, intensity: 0.45, position: [-4, 2.5, 3] },
    rim: { color: 0x7FD4FF, intensity: 1.6, position: [-3, 2.7, 2.5] },
    exposure: 0.92,
    mtoon: { shade: [0.33, 0.40, 0.60], toony: 0.22, rimMultiply: null, rimMix: 0.55, paramRim: [0.55, 0.70, 0.92], fresnel: 2.6, lift: 0 },
  },
  {
    name: '3-warm-soft-term',
    toony: 0.9,
    shift: 0,
    bounce: null,
    hemi: [0xEAF3FF, 0x2A3A55, 0.30],
    key: { color: 0xFFF1DE, intensity: 2.1, position: [3, 5, 5] },
    fill: { color: 0xA9C9FF, intensity: 0.45, position: [-4, 2.5, 3] },
    rim: { color: 0x7FD4FF, intensity: 1.6, position: [-3, 2.7, 2.5] },
    exposure: 0.92,
    mtoon: { shade: [0.46, 0.50, 0.62], toony: 0.45, rimMultiply: null, rimMix: 0.5, paramRim: [0.55, 0.70, 0.92], fresnel: 2.6, lift: 0 },
  },
  {
    name: '4-soft-term-only',
    toony: 0.9,
    shift: 0,
    bounce: null,
    hemi: [0xEBF9FF, 0x18314B, 0.16],
    key: { color: 0xFFFFFF, intensity: 2.3, position: [3, 5, 5] },
    fill: { color: 0xBBD9FF, intensity: 0.14, position: [-4, 2.5, 3] },
    rim: { color: 0x16C9FF, intensity: 1.15, position: [-3, 2.7, 2.5] },
    exposure: 0.95,
    mtoon: { shade: [0.46, 0.50, 0.62], toony: 0.45, rimMultiply: null, rimMix: 0.5, paramRim: [0.55, 0.70, 0.92], fresnel: 2.6, lift: 0 },
  },
  {
    name: '5-warm-plus-rim',
    toony: 0.9,
    shift: 0,
    bounce: { color: 0xFFE2C0, intensity: 0.45, position: [0.5, -1.6, 3.2] },
    hemi: [0xEAF3FF, 0x2A3A55, 0.34],
    key: { color: 0xFFF0D8, intensity: 2.35, position: [3.4, 4.6, 4.4] },
    fill: { color: 0x9FC0FF, intensity: 0.5, position: [-4, 2.2, 2.6] },
    rim: { color: 0x8FD8FF, intensity: 1.9, position: [-3.2, 2.9, 2.2] },
    exposure: 0.9,
    mtoon: { shade: [0.44, 0.48, 0.62], toony: 0.42, rimMultiply: null, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.2, lift: 0.05 },
  },
  {
    name: '6-low-key-contrast',
    toony: 0.9,
    shift: 0,
    bounce: { color: 0xFFE2C0, intensity: 0.45, position: [0.5, -1.6, 3.2] },
    hemi: [0xE6F0FF, 0x22344F, 0.24],
    key: { color: 0xFFF4E4, intensity: 2.6, position: [3.6, 5.2, 4.2] },
    fill: { color: 0x93B6FF, intensity: 0.35, position: [-4, 2.0, 2.4] },
    rim: { color: 0x6FD0FF, intensity: 2.1, position: [-3.4, 3.0, 2.0] },
    exposure: 0.86,
    mtoon: { shade: [0.38, 0.43, 0.60], toony: 0.38, rimMultiply: null, rimMix: 0.5, paramRim: [0.50, 0.66, 0.95], fresnel: 2.2, lift: 0.05 },
  },
  {
    name: '7-cel-bounce',
    toony: 0.9,
    shift: 0,
    bounce: { color: 0xFFE0BC, intensity: 0.5, position: [0.6, -1.4, 3.4] },
    hemi: [0xEAF3FF, 0x2A3A55, 0.28],
    key: { color: 0xFFF0DC, intensity: 2.0, position: [3.2, 4.8, 4.8] },
    fill: { color: 0xA9C9FF, intensity: 0.42, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.7, position: [-3.2, 2.9, 2.2] },
    exposure: 0.93,
    mtoon: { shade: [0.46, 0.50, 0.64], toony: 0.9, rimMultiply: null, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: '8-cel-bounce-pale',
    toony: 0.9,
    shift: 0,
    bounce: { color: 0xFFE0BC, intensity: 0.5, position: [0.6, -1.4, 3.4] },
    hemi: [0xEAF3FF, 0x2A3A55, 0.28],
    key: { color: 0xFFF0DC, intensity: 2.0, position: [3.2, 4.8, 4.8] },
    fill: { color: 0xA9C9FF, intensity: 0.42, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.7, position: [-3.2, 2.9, 2.2] },
    exposure: 0.93,
    mtoon: { shade: [0.54, 0.58, 0.70], toony: 0.9, rimMultiply: null, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: '9-cel-deep-shade',
    toony: 0.9,
    shift: 0,
    bounce: { color: 0xFFE0BC, intensity: 0.42, position: [0.6, -1.4, 3.4] },
    hemi: [0xEAF3FF, 0x22344F, 0.24],
    key: { color: 0xFFF0DC, intensity: 2.15, position: [3.2, 4.8, 4.8] },
    fill: { color: 0xA9C9FF, intensity: 0.4, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.8, position: [-3.2, 2.9, 2.2] },
    exposure: 0.92,
    mtoon: { shade: [0.38, 0.42, 0.60], toony: 0.9, rimMultiply: null, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
]

async function apply(look) {
  await page.evaluate((look) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const renderer = window.__yxzDebug?.renderer?.()

    const hemis = []
    const keys = []
    const fills = []
    const points = []
    scene.traverse((object) => {
      if (object.isHemisphereLight)
        hemis.push(object)
      else if (object.isDirectionalLight && object.intensity > 1)
        keys.push(object)
      else if (object.isDirectionalLight)
        fills.push(object)
      else if (object.isPointLight)
        points.push(object)
    })

    hemis[0]?.color.setHex(look.hemi[0])
    hemis[0]?.groundColor.setHex(look.hemi[1])
    if (hemis[0])
      hemis[0].intensity = look.hemi[2]

    keys[0]?.color.setHex(look.key.color)
    if (keys[0]) {
      keys[0].intensity = look.key.intensity
      keys[0].position.set(...look.key.position)
    }

    fills[0]?.color.setHex(look.fill.color)
    if (fills[0]) {
      fills[0].intensity = look.fill.intensity
      fills[0].position.set(...look.fill.position)
    }

    points[0]?.color.setHex(look.rim.color)
    if (points[0]) {
      points[0].intensity = look.rim.intensity
      points[0].position.set(...look.rim.position)
    }

    if (renderer)
      renderer.toneMappingExposure = look.exposure

    if (look.bounce) {
      let bounce = null
      scene.traverse((object) => {
        if (object.isPointLight && object.name === 'YXZ_Bounce')
          bounce = object
      })
      if (!bounce) {
        bounce = new three.PointLight(0xFFFFFF, 0, 20)
        bounce.name = 'YXZ_Bounce'
        scene.add(bounce)
      }
      bounce.color.setHex(look.bounce.color)
      bounce.intensity = look.bounce.intensity
      bounce.position.set(...look.bounce.position)
    }

    scene.traverse((object) => {
      if (!object.isMesh)
        return
      const material = object.material
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        if (look.mtoon.shade)
          m.shadeColorFactor?.setRGB(...look.mtoon.shade)
        if (look.mtoon.toony !== undefined)
          m.shadingToonyFactor = look.mtoon.toony
        if (look.shift !== undefined)
          m.shadingShiftFactor = look.shift
        if (look.mtoon.rimMultiply !== undefined && look.mtoon.rimMultiply !== null)
          m.rimMultiply = look.mtoon.rimMultiply
        if (look.mtoon.rimMix !== undefined)
          m.rimLightingMixFactor = look.mtoon.rimMix
        if (look.mtoon.paramRim)
          m.parametricRimColorFactor?.setRGB(...look.mtoon.paramRim)
        if (look.mtoon.fresnel !== undefined)
          m.parametricRimFresnelPowerFactor = look.mtoon.fresnel
        if (look.mtoon.lift !== undefined)
          m.parametricRimLiftFactor = look.mtoon.lift
      }
    })
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
