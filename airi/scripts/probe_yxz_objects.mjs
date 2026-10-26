/**
 * Inventory of every object the live YXZ avatar is made of.
 *
 * The render shows shapes on the model that belong to nothing in the
 * design -- sheets above the head, a bar across the forehead -- and
 * nothing in the source tells you which mesh they came from.  The live
 * scene does: every mesh in the VRM is a named object with a material
 * and a bounding box, so the question "what is that shape" is answered
 * by asking the scene.
 *
 * It also reports the MToon factors that decide how the model reads, so
 * a change to the file and a change to the runtime can be compared.
 *
 * Usage: node scripts/probe_yxz_objects.mjs [baseUrl]
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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const inventory = await page.evaluate(() => {
  const three = window.__yxzDebug?.three
  const scene = window.__yxzDebug?.scene?.()
  const out = []
  if (!scene || !three)
    return out
  scene.traverse((object) => {
    if (!object.isMesh)
      return
    const box = new three.Box3().setFromObject(object)
    const size = box.getSize(new three.Vector3())
    const centre = box.getCenter(new three.Vector3())
    const geometry = object.geometry
    const position = geometry.getAttribute('position')
    const list = Array.isArray(object.material) ? object.material : [object.material]
    const materials = []
    for (const m of list) {
      if (!m)
        continue
      materials.push({
        name: m.name,
        type: m.type,
        mtoon: !!m.isMToonMaterial,
        color: m.color ? m.color.getHexString() : null,
        emissive: m.emissive ? m.emissive.getHexString() : null,
        emissiveIntensity: m.emissiveIntensity,
        toony: m.shadingToonyFactor,
        dithering: m.dithering,
        transparent: m.transparent,
        opacity: m.opacity,
        side: m.side,
      })
    }
    out.push({
      name: object.name,
      parent: object.parent?.name ?? null,
      visible: object.visible,
      vertices: position ? position.count : 0,
      triangles: geometry.index ? geometry.index.count / 3 : (position ? position.count : 0) / 3,
      morphs: Object.keys(object.morphTargetDictionary ?? {}),
      min: box.min.toArray().map(v => +v.toFixed(4)),
      max: box.max.toArray().map(v => +v.toFixed(4)),
      size: size.toArray().map(v => +v.toFixed(4)),
      centre: centre.toArray().map(v => +v.toFixed(4)),
      materials: materials,
    })
  })
  return out
})

console.log(JSON.stringify(inventory, null, 2))
await browser.close()
