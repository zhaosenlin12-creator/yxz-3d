/**
 * A/B the YXZ outline pass so dark blotches can be attributed.
 *
 * Once `outlineWidthMode` became a valid string the loader starts building a
 * second, back-face material for every mesh -- including interior parts like
 * the eye balls, the visor liner and the wing panels.  Those sit just under
 * the outer shell, so their expanded back faces can punch through and read as
 * ragged dark smudges rather than a clean silhouette line.  Shadow acne looks
 * almost identical on screen, so guessing from a screenshot is not good
 * enough: this renders the same frozen frame with the outline pass dropped
 * and then with shadows dropped, and the variant that makes the smudge vanish
 * names the culprit.
 *
 * Usage: node scripts/probe_yxz_outline_ab.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-outline-check/ab'

await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
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

// One pose for every variant so the only difference between the shots is the
// switch under test.
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/a-baseline.png` })

const inventory = await page.evaluate(() => {
  const vrm = window.__yxzVrm
  const meshes = []
  const outlineSettings = []
  vrm.scene.traverse((object) => {
    if (object.isMesh && Array.isArray(object.material)) {
      meshes.push({ name: object.name, slots: object.material.length })
      object.material.forEach((material, index) => {
        if (material?._isOutline) {
          outlineSettings.push({
            name: object.name,
            slot: index,
            side: material.side,
            depthTest: material.depthTest,
            depthWrite: material.depthWrite,
            polygonOffset: material.polygonOffset,
            polygonOffsetFactor: material.polygonOffsetFactor,
            outlineWidthFactor: material.outlineWidthFactor,
            skinning: material.skinning,
          })
        }
      })
    }
  })
  return {
    meshes,
    shadowLights: (() => {
      const found = []
      vrm.scene.traverse((object) => {
        if (object.isLight && object.castShadow)
          found.push({ type: object.type, name: object.name, intensity: object.intensity })
      })
      return found
    })(),
    outlineSettings,
  }
})
console.log('INVENTORY', JSON.stringify(inventory))

// Variant B: keep only the surface slot on every mesh, so the outline pass
// never draws.
await page.evaluate(() => {
  window.__yxzVrm.scene.traverse((object) => {
    if (object.isMesh && Array.isArray(object.material))
      object.material = object.material[0]
  })
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/b-no-outline.png` })

// Variant C has to reload, because variant B already overwrote the material
// arrays in place.  Rendering the outline pass on its own shows exactly what
// geometry the ink is being painted onto.
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  window.__yxzVrm.scene.traverse((object) => {
    if (object.isMesh && Array.isArray(object.material)) {
      const outline = object.material.filter(material => material?._isOutline)
      if (outline.length)
        object.material = outline
      else
        object.visible = false
    }
    else if (object.isMesh) {
      object.visible = false
    }
  })
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/c-outline-only.png` })

// Variant D needs the composite back: hide nothing, but stop the surface pass
// from painting while letting it keep writing depth.  Whatever still shows up
// is outline geometry that genuinely won the depth test, so the remaining ink
// marks exactly which parts of the body the outline is stealing.
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh || !Array.isArray(object.material))
      return
    for (const material of object.material) {
      if (material?._isOutline)
        material.uniforms.outlineColorFactor.value.setRGB(1, 0, 0)
      else
        material.colorWrite = false
    }
  })
})
await page.waitForTimeout(2500)
await canvas.screenshot({ path: `${outDir}/d-outline-wins-depth.png` })

await browser.close()
console.log('OUT', outDir)
