/**
 * Which layer makes which mark.
 *
 * The mouth is three pieces of geometry stacked on top of each other:
 * the face, the plate that carries the painted lips, and the dark
 * lining behind the opening.  A pale sliver between the lips can be
 * any of them, and the three need different fixes, so the mouth is
 * shot with one layer hidden at a time.
 *
 * Usage: node scripts/shot_yxz_mouth_layers.mjs [baseUrl] [outDir]
 */

import { mkdirSync, readdirSync } from 'node:fs'
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

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const outDir = process.argv[3] ?? 'docs/yxz-audit/mouth-layers'

const LAYERS = [
  { name: 'all', hide: [] },
  { name: 'no-cavity', hide: ['YXZ_MouthCavity'] },
  { name: 'no-plate', hide: ['YXZ_Mouth'] },
  { name: 'plate-only', hide: ['YXZ_MouthCavity', 'tripo_mesh'] },
]

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
})
await page.waitForTimeout(1500)

const place = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const camera = debug?.camera?.()
  const scene = debug?.scene?.()
  const rect = document.querySelector('.yxz-real-model-canvas canvas').getBoundingClientRect()
  let mouth = null
  scene?.traverse((object) => {
    if (object.isMesh && object.name === 'YXZ_Mouth')
      mouth = object
  })
  if (!mouth || !camera)
    return null
  const centre = new THREE.Vector3()
  new THREE.Box3().setFromObject(mouth).getCenter(centre)
  const projected = centre.project(camera)
  return {
    origin: { x: rect.x, y: rect.y },
    size: { w: rect.width, h: rect.height },
    px: [
      (projected.x * 0.5 + 0.5) * rect.width,
      (-projected.y * 0.5 + 0.5) * rect.height,
    ],
  }
})
console.log(`MOUTH ${JSON.stringify(place)}`)

mkdirSync(outDir, { recursive: true })
for (const layer of LAYERS) {
  await page.evaluate((hide) => {
    const scene = window.__yxzDebug?.scene?.()
    scene?.traverse((object) => {
      if (!object.isMesh)
        return
      object.visible = !hide.includes(object.name)
    })
  }, layer.hide)
  await page.waitForTimeout(1400)
  const file = path.join(outDir, `${layer.name}.png`)
  await page.screenshot({
    path: file,
    clip: {
      x: place.origin.x,
      y: place.origin.y,
      width: place.size.w,
      height: place.size.h,
    },
  })
  console.log(`SHOT ${file}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
