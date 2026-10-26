/**
 * Is the pale line along the lips a gap, or is it shading?
 *
 * A pale line down the middle of the mouth can be a hole through the
 * geometry -- the lip edges parted and the background showed through --
 * or it can be the crease at the edge of the lips catching the light.
 * The two need completely different fixes, and the difference is one
 * picture: the page behind the character is made a colour that cannot
 * be mistaken for either, and a gap takes the colour while a crease
 * does not.
 *
 * Usage: node scripts/probe_yxz_mouth_gap.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-audit/mouth-gap'

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
  document.body.style.setProperty('background', '#ff00a0', 'important')
  // The canvas is opaque, so the page behind it never shows through.
  // The colour has to be put into the renderer itself, or a gap in the
  // geometry shows the clear colour and the test says nothing.
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer) {
    renderer.setClearColor(0xff00a0, 1)
    const composer = window.__yxzDebug?.composer?.()
    composer?.setClearColor?.(0xff00a0, 1)
    const gl = renderer.getContext()
    gl.clearColor(1, 0, 0.63, 1)
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
  }
  window.__yxzDebug?.freeze(true)
})
await page.waitForTimeout(1800)

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
const file = path.join(outDir, 'magenta.png')
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
console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
