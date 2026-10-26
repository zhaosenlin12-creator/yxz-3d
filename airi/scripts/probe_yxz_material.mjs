/**
 * Read the MToon materials off the live character, then try a grid of
 * shading settings against the face close-up.
 *
 * The saw-tooth along the jaw is two sheets of the scan crossing each other.
 * The geometry cannot be fixed from here, but the contrast can: MToon
 * replaces a shaded pixel's colour with the flat shade colour, so every
 * stray triangle that crosses the terminator flips to that colour.  The
 * darker the shade colour and the harder the terminator, the louder the
 * fringe gets.  This probe therefore measures how the fringe reads for a
 * range of shade colours and toony factors, and prints the material state
 * that decides the rest.
 *
 * Usage: node scripts/probe_yxz_material.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-material'
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

const state = await page.evaluate(() => {
  const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
  const materials = []
  scene.traverse((object) => {
    if (!object.isMesh)
      return
    const material = object.material
    for (const m of Array.isArray(material) ? material : [material]) {
      if (!m || materials.some(e => e.uuid === m.uuid))
        continue
      materials.push({
        name: object.name || '(unnamed)',
        type: m.type,
        isMToon: Boolean(m.isMToonMaterial),
        transparent: m.transparent,
        opacity: m.opacity,
        alphaTest: m.alphaTest,
        alphaHash: m.alphaHash,
        depthWrite: m.depthWrite,
        depthTest: m.depthTest,
        side: m.side,
        blending: m.blending,
        polygonOffset: m.polygonOffset,
        polygonOffsetFactor: m.polygonOffsetFactor,
        visible: m.visible,
        color: m.color?.getHexString?.() ?? null,
        hasMap: Boolean(m.map),
        mtoon: m.isMToonMaterial
          ? {
              shade: m.shadeColorFactor?.getHexString?.() ?? null,
              toony: m.shadingToonyFactor,
              shift: m.shadingShiftFactor,
              rimMultiply: m.rimMultiply,
              rimMix: m.rimLightingMixFactor,
              paramRim: m.parametricRimColorFactor?.getHexString?.() ?? null,
              fresnel: m.parametricRimFresnelPowerFactor,
              lift: m.parametricRimLiftFactor,
              spec: m.specularFactor,
              specColor: m.specularColorFactor?.getHexString?.() ?? null,
              matcap: m.matcapFactor,
              outlineWidth: m.outlineWidth,
              outlineColor: m.outlineColor?.getHexString?.() ?? null,
              outlineMix: m.outlineLightingMixFactor,
            }
          : null,
      })
    }
  })
  return materials
})

console.log('MATERIALS')
console.log(JSON.stringify(state, null, 1))

const FACE = { left: 380, top: 250, width: 320, height: 230 }

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    await sharp(file)
      .extract(FACE)
      .resize({ width: 1200, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-face.png`))
  }
  console.log('SHOT', name)
}

async function setState(next) {
  await page.evaluate((next) => {
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    scene.traverse((object) => {
      if (!object.isMesh)
        return
      const material = object.material
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        if (next.shade)
          m.shadeColorFactor?.setRGB(next.shade[0], next.shade[1], next.shade[2])
        if (next.toony !== undefined)
          m.shadingToonyFactor = next.toony
        if (next.shift !== undefined)
          m.shadingShiftFactor = next.shift
        if (next.rimMultiply !== undefined)
          m.rimMultiply = next.rimMultiply
        if (next.rimMix !== undefined)
          m.rimLightingMixFactor = next.rimMix
        if (next.paramRim)
          m.parametricRimColorFactor?.setRGB(next.paramRim[0], next.paramRim[1], next.paramRim[2])
        if (next.fresnel !== undefined)
          m.parametricRimFresnelPowerFactor = next.fresnel
        if (next.lift !== undefined)
          m.parametricRimLiftFactor = next.lift
      }
    })
  }, next)
  await page.waitForTimeout(2500)
}

const grid = [
  ['1-current', { shade: [0.33, 0.40, 0.60], toony: 0.22 }],
  ['2-lighter-shade', { shade: [0.55, 0.60, 0.70], toony: 0.22 }],
  ['3-pale-shade', { shade: [0.72, 0.76, 0.84], toony: 0.22 }],
  ['4-soft-toony', { shade: [0.33, 0.40, 0.60], toony: 0.55 }],
  ['5-pale-and-soft', { shade: [0.66, 0.70, 0.80], toony: 0.55 }],
  ['6-pale-soft-lowrim', { shade: [0.66, 0.70, 0.80], toony: 0.55, rimMultiply: 0.35 }],
]

for (const [name, next] of grid) {
  await setState(next)
  await shoot(name)
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
