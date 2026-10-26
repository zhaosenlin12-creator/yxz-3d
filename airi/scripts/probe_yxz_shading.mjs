/**
 * A/B the shading and the outline of the YXZ avatar in one browser session.
 *
 * The "broken up" look on this character is not one bug but three, and they
 * have to be told apart before any of them is fixed:
 *
 *   white smears   MToon's rim term is `rimColor * pow(saturate(1 - dot(view,
 *                  normal)), power)`.  A surface whose shading normal points
 *                  away from the camera saturates that expression to 1, so
 *                  the rim colour is added at full strength.  The rim colour
 *                  here is near-white and the shell is near-white, so those
 *                  patches clip to white and read as paint smears.
 *   flat body      `shadeColorFactor` only darkens the shadow side to ~75%
 *                  of the lit side, so the cel ramp has almost no depth.
 *   dashed outline three r183's `OutlinePass` runs the edge detection on a
 *                  mask that was downsampled by `downSampleRatio` (2 by
 *                  default).  A one-pixel antenna is half a pixel after that
 *                  downsample and drops out of the detection, which is what
 *                  breaks the line into dashes.
 *
 * Every variant below is applied to the live scene, so the comparison is
 * pixel-for-pixel on the same pose.
 *
 * Usage: node scripts/probe_yxz_shading.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-shading'
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

// What the runtime actually loaded, so the numbers in the report are the
// numbers the shader is using and not the ones the build script wrote.
const materialInfo = await page.evaluate(() => {
  const out = []
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      if (!material)
        continue
      out.push({
        mesh: object.name,
        type: material.type,
        rim: material.parametricRimColorFactor?.getHexString?.() ?? null,
        rimMix: material.rimLightingMixFactor ?? null,
        fresnel: material.parametricRimFresnelPowerFactor ?? material.uniforms?.parametricRimFresnelPowerFactor?.value ?? null,
        lift: material.parametricRimLiftFactor ?? material.uniforms?.parametricRimLiftFactor?.value ?? null,
        shade: material.shadeColorFactor?.getHexString?.() ?? null,
        toony: material.shadingToonyFactor ?? material.uniforms?.shadingToonyFactor?.value ?? null,
        side: material.side,
      })
    }
  })
  return out
})
console.log('MATERIALS', JSON.stringify(materialInfo, null, 2))

async function park() {
  await page.evaluate(() => {
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  // The headless renderer manages about one frame a second, so the composer
  // needs a few seconds to redraw the parked pose.
  await page.waitForTimeout(6000)
}

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    const { width, height } = await sharp(file).metadata()
    // The head sits in the upper half of the frame; the jaw smear and the
    // helmet outline are the two things worth zooming into.
    await sharp(file)
      .extract({
        left: Math.round(width * 0.2),
        top: Math.round(height * 0.04),
        width: Math.round(width * 0.6),
        height: Math.round(height * 0.46),
      })
      .resize({ width: 900, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-head.png`))
  }
  console.log('SHOT', name)
}

async function applyMaterial(patch) {
  await page.evaluate((patch) => {
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh)
        return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      for (const material of list) {
        if (!material)
          continue
        for (const [key, value] of Object.entries(patch)) {
          const target = material[key] ?? material.uniforms?.[key]?.value
          if (!target)
            continue
          if (target.isColor)
            target.setRGB(value[0], value[1], value[2])
          else if (typeof target === 'number')
            material[key] = value
          else if (target.set)
            target.set(value)
        }
      }
    })
  }, patch)
}

await park()
await shoot('1-as-is')

// Hypothesis test: if the white smears are the rim term, killing the rim
// colour has to make them disappear.
await applyMaterial({ parametricRimColorFactor: [0, 0, 0] })
await page.waitForTimeout(4000)
await shoot('2-rim-off')

// A rim that stays a light but not blown-out cool tone, tight to the
// silhouette instead of flooding every grazing surface.
await applyMaterial({
  parametricRimColorFactor: [0.42, 0.55, 0.74],
  parametricRimFresnelPowerFactor: 4.0,
  rimLightingMixFactor: 0.35,
})
await page.waitForTimeout(4000)
await shoot('3-rim-tight')

// Same rim, but with a shadow side that actually reads as a shadow.
await applyMaterial({ shadeColorFactor: [0.40, 0.48, 0.66], shadingToonyFactor: 0.62 })
await page.waitForTimeout(4000)
await shoot('4-rim-tight-shade')

// What the outline pass contributes on its own.
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(4000)
await shoot('5-no-outline')

// Full-resolution edge detection.
await page.evaluate(() => {
  const debug = window.__yxzDebug
  const pass = debug?.outlinePass?.()
  const renderer = debug?.renderer?.()
  if (!pass || !renderer)
    return
  pass.enabled = true
  pass.downSampleRatio = 1
  pass.setSize(renderer.domElement.width, renderer.domElement.height)
})
await page.waitForTimeout(4000)
await shoot('6-outline-fullres')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
