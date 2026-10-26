/**
 * Sweep the lighting rig and score each look on how much form it shows.
 *
 * The character is a white figure, and a white figure has nowhere to
 * go: push the key light up and the lit side clips to flat white, the
 * panels stop reading as panels and the whole character turns into a
 * paper cut-out.  That is the "shattered" look -- not broken geometry,
 * but a surface with no gradient left on it, so every seam reads as a
 * hard line and nothing reads as a volume.
 *
 * So each look is scored rather than eyeballed:
 *
 *   blown   the share of the character's pixels that are at the top of
 *           the range, which is the flat area that has lost its form
 *   spread  the standard deviation of the character's brightness, which
 *           is how much shading is left to describe the shape
 *   range   the distance between the darkest and brightest tenth of the
 *           character, which is the full tonal range in use
 *
 * Usage: node scripts/sweep_yxz_form.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-form-sweep'
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
  // The canvas is transparent where the character is not, so the page
  // shows through.  Painting the page magenta makes the background
  // pixels trivially separable from the character's own.
  for (let node = canvas; node; node = node.parentElement) {
    node.style.setProperty('background', '#FF00FF', 'important')
    node.style.setProperty('background-image', 'none', 'important')
  }
  document.documentElement.style.setProperty('background', '#FF00FF', 'important')
  document.body.style.setProperty('background', '#FF00FF', 'important')
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const canvas = page.locator('.yxz-real-model-canvas canvas')

// The rig the scene builds, and the MToon parameters on top of it.
const looks = [
  {
    name: 'a-current',
    hemi: [0xEAF3FF, 0x2A3A55, 0.28],
    key: { color: 0xFFF0DC, intensity: 2.0, position: [3.2, 4.8, 4.8] },
    fill: { color: 0xA9C9FF, intensity: 0.42, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.7, position: [-3.2, 2.9, 2.2] },
    bounce: { color: 0xFFE0BC, intensity: 0.5, position: [0.6, -1.4, 3.4] },
    exposure: 0.93,
    mtoon: { shade: [0.46, 0.50, 0.64], toony: 0.9, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: 'b-lower-key',
    hemi: [0xEAF3FF, 0x2A3A55, 0.24],
    key: { color: 0xFFF0DC, intensity: 1.45, position: [3.2, 4.8, 4.8] },
    fill: { color: 0xA9C9FF, intensity: 0.34, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.5, position: [-3.2, 2.9, 2.2] },
    bounce: { color: 0xFFE0BC, intensity: 0.34, position: [0.6, -1.4, 3.4] },
    exposure: 0.88,
    mtoon: { shade: [0.44, 0.48, 0.62], toony: 0.9, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: 'c-deep-shade',
    hemi: [0xE4EFFF, 0x24344C, 0.20],
    key: { color: 0xFFF2E2, intensity: 1.25, position: [3.2, 4.8, 4.8] },
    fill: { color: 0x9EC2FF, intensity: 0.30, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.6, position: [-3.2, 2.9, 2.2] },
    bounce: { color: 0xFFE0BC, intensity: 0.28, position: [0.6, -1.4, 3.4] },
    exposure: 0.86,
    mtoon: { shade: [0.40, 0.44, 0.60], toony: 0.92, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: 'd-soft-ramp',
    hemi: [0xE4EFFF, 0x24344C, 0.22],
    key: { color: 0xFFF2E2, intensity: 1.35, position: [3.2, 4.8, 4.8] },
    fill: { color: 0x9EC2FF, intensity: 0.32, position: [-4, 2.4, 2.8] },
    rim: { color: 0x8FD8FF, intensity: 1.6, position: [-3.2, 2.9, 2.2] },
    bounce: { color: 0xFFE0BC, intensity: 0.30, position: [0.6, -1.4, 3.4] },
    exposure: 0.88,
    mtoon: { shade: [0.42, 0.46, 0.62], toony: 0.72, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
  {
    name: 'e-side-key',
    hemi: [0xE4EFFF, 0x24344C, 0.22],
    key: { color: 0xFFF2E2, intensity: 1.5, position: [4.2, 3.4, 3.0] },
    fill: { color: 0x9EC2FF, intensity: 0.34, position: [-3.6, 2.2, 3.2] },
    rim: { color: 0x8FD8FF, intensity: 1.9, position: [-3.2, 3.2, 1.6] },
    bounce: { color: 0xFFE0BC, intensity: 0.30, position: [0.6, -1.6, 3.0] },
    exposure: 0.88,
    mtoon: { shade: [0.42, 0.46, 0.62], toony: 0.9, rimMix: 0.5, paramRim: [0.52, 0.68, 0.95], fresnel: 2.3, lift: 0.04 },
  },
]

/**
 * Put the rig in a known state.  The scene builds its own lights, so
 * they are found by type rather than by name, and the ones that are not
 * named in the look are left where they are.
 */
async function apply(look) {
  await page.evaluate((look) => {
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const renderer = window.__yxzDebug?.renderer?.()
    if (!scene)
      return

    let key = null
    let fill = null
    let hemi = null
    const points = []
    scene.traverse((object) => {
      if (object.isDirectionalLight) {
        if (!key)
          key = object
        else if (!fill)
          fill = object
      }
      else if (object.isHemisphereLight) {
        hemi = object
      }
      else if (object.isPointLight) {
        points.push(object)
      }
    })

    if (key) {
      key.color.setHex(look.key.color)
      key.intensity = look.key.intensity
      key.position.set(...look.key.position)
    }
    if (fill) {
      fill.color.setHex(look.fill.color)
      fill.intensity = look.fill.intensity
      fill.position.set(...look.fill.position)
    }
    if (hemi) {
      hemi.color.setHex(look.hemi[0])
      hemi.groundColor.setHex(look.hemi[1])
      hemi.intensity = look.hemi[2]
    }
    // The point lights are the rim and the bounce, in the order the
    // scene adds them.
    if (points[0]) {
      points[0].color.setHex(look.rim.color)
      points[0].intensity = look.rim.intensity
      points[0].position.set(...look.rim.position)
    }
    if (points[1] && look.bounce) {
      points[1].color.setHex(look.bounce.color)
      points[1].intensity = look.bounce.intensity
      points[1].position.set(...look.bounce.position)
    }
    if (renderer)
      renderer.toneMappingExposure = look.exposure

    scene.traverse((object) => {
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        m.shadeColorFactor.setRGB(...look.mtoon.shade)
        m.shadingToonyFactor = look.mtoon.toony
        m.rimLightingMixFactor = look.mtoon.rimMix
        m.parametricRimColorFactor.setRGB(...look.mtoon.paramRim)
        m.parametricRimFresnelPowerFactor = look.mtoon.fresnel
        m.parametricRimLiftFactor = look.mtoon.lift
      }
    })
  }, look)
  await page.waitForTimeout(2200)
}

/** Score the character's own pixels: how much of it is flat white. */
function score(file) {
  return sharp(file).raw().toBuffer({ resolveWithObject: true }).then(({ data, info }) => {
    const { width, height, channels } = info
    const lumas = []
    for (let i = 0; i < width * height; i++) {
      const p = i * channels
      const r = data[p]
      const g = data[p + 1]
      const b = data[p + 2]
      // The page behind the canvas is magenta, so the background is
      // told apart from the character by its hue.
      if (r > 200 && b > 200 && g < 90)
        continue
      lumas.push(0.2126 * r + 0.7152 * g + 0.0722 * b)
    }
    if (!lumas.length)
      return null
    const sorted = Float64Array.from(lumas).sort()
    const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length
    const variance = sorted.reduce((a, b) => a + (b - mean) ** 2, 0) / sorted.length
    const blown = sorted.filter(v => v >= 248).length / sorted.length
    const low = sorted[Math.floor(sorted.length * 0.05)]
    const high = sorted[Math.floor(sorted.length * 0.95)]
    return {
      pixels: sorted.length,
      mean: Number(mean.toFixed(1)),
      spread: Number(Math.sqrt(variance).toFixed(1)),
      range: Number((high - low).toFixed(1)),
      blown: Number((blown * 100).toFixed(2)),
    }
  })
}

for (const look of looks) {
  await apply(look)
  const file = path.join(outDir, `${look.name}.png`)
  await canvas.screenshot({ path: file })
  const result = await score(file)
  console.log('LOOK', look.name, JSON.stringify(result))
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
