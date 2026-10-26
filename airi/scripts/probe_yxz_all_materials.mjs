/**
 * Print every material on the running character, not only the body's.
 *
 * The halo, the eyes and the mouth are objects of their own with their own
 * materials, and the body's own material tells you nothing about them.  This
 * dumps all of them, so the numbers written against a material are written
 * against the name the running page actually uses.
 *
 * Usage: node scripts/probe_yxz_all_materials.mjs [baseUrl]
 */

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
const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 800, height: 600 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(() => {
  const rows = []
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      if (!material)
        continue
      const uniforms = material.uniforms ?? {}
      const row = {
        mesh: object.name,
        material: material.name,
        type: material.type,
        visible: object.visible,
        renderOrder: object.renderOrder,
        side: material.side,
      }
      for (const key of ['color', 'litFactor', 'shadeColorFactor', 'emissive', 'emissiveIntensity',
        'shadingToonyFactor', 'parametricRimColorFactor', 'rimLightingMixFactor',
        'parametricRimFresnelPowerFactor', 'parametricRimLiftFactor', 'matcapFactor',
        'reflectanceFactor', 'shadingShiftFactor', 'giEqualizationFactor', 'outlineWidthFactor']) {
        const value = uniforms[key]?.value
        if (value?.isColor)
          row[key] = `#${value.getHexString()}`
        else if (typeof value === 'number')
          row[key] = value
        else if (value !== undefined)
          row[key] = String(value)
      }
      row.hasMap = !!material.map
      row.mapName = material.map?.name ?? null
      row.hasEmissiveMap = !!material.emissiveMap
      row.emissiveMapName = material.emissiveMap?.name ?? null
      rows.push(row)
    }
  })
  return rows
})

console.log(JSON.stringify(report, null, 2))
await browser.close()
