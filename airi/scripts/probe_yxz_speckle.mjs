/**
 * Find out where the speckle on the visor comes from.
 *
 * The face close-up shows a band of white speckle across the dark visor and
 * a row of saw-tooth triangles along its lower edge.  The base colour atlas
 * is clean there and the normal map is clean there, so the speckle is not
 * texture and not geometry: it is produced by the shading.
 *
 * Two candidates, and they look the same in a still but behave nothing
 * alike:
 *
 *   shadow acne   the surface shadows itself, because the shadow map is
 *                 coarser than the surface it is drawn from
 *   dither        MToon dithers the cel terminator, and the terminator
 *                 lands exactly across the visor
 *
 * The probe switches one thing at a time and crops the face every time, so
 * whichever switch removes the speckle names the cause.
 *
 * Usage: node scripts/probe_yxz_speckle.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-speckle'
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
await page.waitForTimeout(5000)

const canvas = page.locator('.yxz-real-model-canvas canvas')
const box = await canvas.boundingBox()
console.log('CANVAS', Math.round(box.width), Math.round(box.height))

/** The face, scaled off the canvas so the crop survives a resize. */
const FACE = {
  left: Math.round(box.width * 0.365),
  top: Math.round(box.height * 0.275),
  width: Math.round(box.width * 0.30),
  height: Math.round(box.height * 0.255),
}

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    await sharp(file)
      .extract(FACE)
      .resize({ width: 1100, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-face.png`))
  }
  console.log('SHOT', name)
}

const variants = [
  ['1-baseline', {}],
  ['2-no-shadow', { shadow: false }],
  ['3-big-shadow-map', { mapSize: 4096 }],
  ['4-no-normal-bias', { normalBias: 0 }],
  ['5-big-normal-bias', { normalBias: 0.12 }],
  ['6-soft-shadow', { shadowType: 'soft' }],
  ['7-no-dither', { dither: false }],
  ['8-toony-0', { toony: 0 }],
  ['9-no-key', { key: false }],
  ['10-no-rim', { rim: false }],
  ['11-no-bounce', { bounce: false }],
  ['12-no-fill', { fill: false }],
  ['13-no-hemi', { hemi: false }],
]

async function apply(state) {
  await page.evaluate((state) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.()
    const renderer = window.__yxzDebug?.renderer?.()
    if (renderer) {
      if (state.shadow === false) {
        renderer.shadowMap.enabled = false
      }
      else {
        renderer.shadowMap.enabled = true
        if (state.shadowType === 'soft')
          renderer.shadowMap.type = three.PCFSoftShadowMap
        else
          renderer.shadowMap.type = three.PCFShadowMap
      }
    }
    scene?.traverse((object) => {
      if (object.isDirectionalLight) {
        if (state.key === false && object.castShadow)
          object.visible = false
        else
          object.visible = true
        if (object.castShadow && state.mapSize && object.shadow.mapSize.x !== state.mapSize) {
          object.shadow.mapSize.set(state.mapSize, state.mapSize)
          object.shadow.map?.dispose()
          object.shadow.map = null
        }
        if (state.normalBias !== undefined)
          object.shadow.normalBias = state.normalBias
      }
      else if (object.isPointLight) {
        // The rim is the cyan one, the bounce the warm one.
        const warm = object.color.r > object.color.b
        if (warm && state.bounce === false)
          object.visible = false
        else if (!warm && state.rim === false)
          object.visible = false
        else
          object.visible = true
      }
      else if (object.isHemisphereLight) {
        if (state.hemi === false)
          object.visible = false
        else
          object.visible = true
      }
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (m?.isMToonMaterial) {
          if (state.toony !== undefined)
            m.shadingToonyFactor = state.toony
          if (state.dither === false)
            m.dithering = false
        }
      }
    })
    if (renderer)
      renderer.shadowMap.needsUpdate = true
  }, state)
  await page.waitForTimeout(2200)
}

for (const [name, state] of variants) {
  await apply(state)
  await shoot(name)
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
await browser.close()
