/**
 * A/B the face close-up.
 *
 * The dark visor of the helmet ends in a row of saw-tooth triangles and its
 * upper lip is a band of dithered speckle, and together they are what makes
 * the character read as shattered rather than drawn.  Both symptoms sit on
 * the boundary between the lit and the shaded part of the face, so this
 * probe switches one thing at a time and crops the face every time:
 *
 *   no shadow       the saw-tooth is the shadow map
 *   soft toony      the saw-tooth is the hard cel terminator
 *   big map         the saw-tooth is shadow-map resolution
 *   flat shade      the saw-tooth is the shade colour
 *
 * Usage: node scripts/probe_yxz_face_ab.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-face-ab'
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

/** The face, at three times the size, so a one-pixel wobble is visible. */
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

function eachMToon(fn) {
  window.__yxzDebug?.scene?.().traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const m of Array.isArray(material) ? material : [material]) {
      if (m?.isMToonMaterial)
        fn(m)
    }
  })
}

/*
 * Every variant sets the whole state, so the shots stay comparable: a
 * change from one shot to the next is always the one thing that moved and
 * never the residue of the shot before it.
 */
const variants = [
  ['1-baseline', { toony: 0.22, shade: [0.33, 0.40, 0.60], shadow: true, cast: true, map: 1024, soft: false }],
  ['10-basic-map', { toony: 0.22, shade: [0.33, 0.40, 0.60], shadow: true, cast: true, map: 1024, soft: false, mode: 'basic-map' }],
  ['11-basic-map-double', { toony: 0.22, shade: [0.33, 0.40, 0.60], shadow: true, cast: true, map: 1024, soft: false, mode: 'basic-map-double' }],
  ['12-normal', { toony: 0.22, shade: [0.33, 0.40, 0.60], shadow: true, cast: true, map: 1024, soft: false, mode: 'normal' }],
  ['13-basic-white', { toony: 0.22, shade: [0.33, 0.40, 0.60], shadow: true, cast: true, map: 1024, soft: false, mode: 'basic-white' }],
]

async function apply(state) {
  await page.evaluate((state) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const renderer = window.__yxzDebug?.renderer?.()
    if (renderer) {
      renderer.shadowMap.enabled = state.shadow
      renderer.shadowMap.type = state.soft ? three.PCFSoftShadowMap : three.PCFShadowMap
    }
    window.__yxzDebug?.scene?.().traverse((object) => {
      if (object.isDirectionalLight) {
        object.castShadow = state.cast
        if (object.shadow && object.shadow.mapSize.x !== state.map) {
          object.shadow.mapSize.set(state.map, state.map)
          object.shadow.map?.dispose()
          object.shadow.map = null
        }
      }
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (m?.isMToonMaterial) {
          m.shadingToonyFactor = state.toony
          m.shadeColorFactor?.setRGB(state.shade[0], state.shade[1], state.shade[2])
        }
      }
    })
    if (renderer)
      renderer.shadowMap.needsUpdate = true

    if (state.mode) {
      scene.traverse((object) => {
        if (!object.isMesh)
          return
        const material = object.material
        const source = Array.isArray(material) ? material[0] : material
        if (state.mode === 'basic-map') {
          object.material = new three.MeshBasicMaterial({
            map: source?.map ?? null,
            color: 0xFFFFFF,
            side: three.FrontSide,
            transparent: false,
          })
        }
        else if (state.mode === 'basic-map-double') {
          object.material = new three.MeshBasicMaterial({
            map: source?.map ?? null,
            color: 0xFFFFFF,
            side: three.DoubleSide,
            transparent: false,
          })
        }
        else if (state.mode === 'normal') {
          object.material = new three.MeshNormalMaterial({
            side: three.FrontSide,
            transparent: false,
            flatShading: false,
          })
        }
        else if (state.mode === 'basic-white') {
          object.material = new three.MeshBasicMaterial({
            color: 0xBBBBBB,
            side: three.FrontSide,
            transparent: false,
          })
        }
      })
    }
  }, state)
}

for (const [name, state] of variants) {
  await apply(state)
  await page.waitForTimeout(3000)
  await shoot(name)
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
