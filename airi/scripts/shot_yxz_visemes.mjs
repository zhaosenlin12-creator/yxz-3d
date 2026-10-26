/**
 * The mouth, in every shape it is asked to make.
 *
 * A closed mouth can hide almost anything: the white dome that used to
 * sit in the middle of the lips only appeared when the mouth opened.
 * So the mouth is checked in all four vowel shapes, on the live page,
 * through the page's own renderer, and each frame is cropped to the
 * mouth so that a defect the size of a grain of rice is still a
 * subject rather than a speck.
 *
 * Usage: node scripts/shot_yxz_visemes.mjs [baseUrl] [outDir]
 */

import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
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
const outDir = process.argv[3] ?? 'docs/yxz-audit/visemes-live'
const VISEMES = ['closed', 'aa', 'ih', 'ou', 'ee']

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

// Where the mouth is, on the screen, in this canvas's own pixels.
const place = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const camera = debug?.camera?.()
  const scene = debug?.scene?.()
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const rect = canvas.getBoundingClientRect()
  let mouth = null
  scene?.traverse((object) => {
    if (object.isMesh && object.name === 'YXZ_Mouth')
      mouth = object
  })
  if (!mouth || !camera)
    return null
  const box = new THREE.Box3().setFromObject(mouth)
  const centre = new THREE.Vector3()
  box.getCenter(centre)
  const projected = centre.project(camera)
  return {
    canvas: { w: rect.width, h: rect.height },
    origin: { x: rect.x, y: rect.y },
    px: [
      (projected.x * 0.5 + 0.5) * rect.width,
      (-projected.y * 0.5 + 0.5) * rect.height,
    ],
    world: centre.toArray(),
  }
})
console.log(`MOUTH ${JSON.stringify(place)}`)

mkdirSync(outDir, { recursive: true })

for (const viseme of VISEMES) {
  await page.evaluate((name) => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return
    // The render loop drives the mouth itself, so it is taken out of
    // the loop's hands first; otherwise the next frame puts the mouth
    // back to whatever the character's status says it should be.
    if (!manager.__yxzPatched) {
      const original = manager.setValue.bind(manager)
      manager.setValue = (expression, value) => {
        if (['aa', 'ih', 'ou', 'ee'].includes(expression))
          return
        original(expression, value)
      }
      manager.__yxzPatched = true
      manager.__yxzOriginal = original
    }
    const original = manager.__yxzOriginal
    for (const expression of ['aa', 'ih', 'ou', 'ee'])
      original(expression, expression === name ? 1 : 0)
  }, viseme)
  await page.waitForTimeout(1400)
  const file = path.join(outDir, `${viseme}.png`)
  // The page is shot rather than the canvas element: an element shot
  // waits for the element to stop moving, and a canvas that is being
  // drawn to never does.
  await page.screenshot({
    path: file,
    clip: {
      x: place.origin.x,
      y: place.origin.y,
      width: place.canvas.w,
      height: place.canvas.h,
    },
  })
  console.log(`SHOT ${file}`)
}

if (place)
  writeFileSync(path.join(outDir, 'place.json'), JSON.stringify(place, null, 2))

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
