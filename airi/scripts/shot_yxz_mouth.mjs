/**
 * The mouth, at the two scales that matter.
 *
 * A millimetre of geometry is a defect in a close-up and invisible from
 * the stage, so a close-up alone cannot decide whether the mouth is
 * finished -- it can only say what is wrong with it.  These two shots
 * answer the two questions at once: the wide one is what the user
 * actually sees, and the tight one is what the defect is.
 *
 * Usage: node scripts/shot_yxz_mouth.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-audit/mouth-live'

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

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')

// The canvas is drawn every frame, so an element screenshot never
// settles and the capture times out waiting for it to.  A page
// screenshot of the canvas's own box does not wait for anything.
const clip = await (async () => {
  const box = await canvas.boundingBox()
  if (!box)
    return undefined
  return {
    x: Math.round(box.x),
    y: Math.round(box.y),
    width: Math.round(box.width),
    height: Math.round(box.height),
  }
})()

// The wide shot is the stage's own camera, untouched.
await page.waitForTimeout(1200)
await page.screenshot({ path: path.join(outDir, 'stage.png'), clip, timeout: 120_000 })
console.log(`SHOT ${path.join(outDir, 'stage.png')}`)

// The mouth's own place, measured from the mesh rather than guessed.
const place = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const scene = debug?.scene?.() ?? window.__yxzVrm?.scene
  if (!scene || !THREE)
    return null
  let mouth = null
  scene.traverse((object) => {
    if (object.isMesh && /mouth/i.test(object.name))
      mouth ??= object
  })
  if (!mouth)
    return null
  const box = new THREE.Box3().setFromObject(mouth)
  const centre = new THREE.Vector3()
  box.getCenter(centre)
  const size = new THREE.Vector3()
  box.getSize(size)
  const forward = new THREE.Vector3()
  mouth.getWorldDirection(forward)
  return {
    centre: centre.toArray(),
    size: size.toArray(),
    forward: forward.toArray(),
  }
})
console.log(`MOUTH ${JSON.stringify(place)}`)

if (place) {
  const [cx, cy, cz] = place.centre
  const [fx, fy, fz] = place.forward
  const shots = [
    { name: 'mouth-wide', dist: 0.16, tilt: 0 },
    { name: 'mouth-tight', dist: 0.085, tilt: 0 },
    { name: 'mouth-oblique', dist: 0.11, tilt: 0.55 },
  ]
  for (const shot of shots) {
    await page.evaluate(([c, f, s]) => {
      const debug = window.__yxzDebug
      const camera = debug?.camera?.()
      if (!camera)
        return
      const THREE = debug.three
      const centre = new THREE.Vector3(c[0], c[1], c[2])
      const forward = new THREE.Vector3(f[0], f[1], f[2])
      if (forward.lengthSq() < 1e-6)
        forward.set(0, 0, 1)
      forward.normalize()
      const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), forward).normalize()
      const eye = centre.clone()
        .addScaledVector(forward, s.dist)
        .addScaledVector(right, s.dist * s.tilt)
        .addScaledVector(new THREE.Vector3(0, 1, 0), s.dist * s.tilt * 0.35)
      camera.position.copy(eye)
      camera.lookAt(centre)
      camera.updateProjectionMatrix()
    }, [[cx, cy, cz], [fx, fy, fz], shot])
    await page.waitForTimeout(1400)
    const file = path.join(outDir, `${shot.name}.png`)
    await page.screenshot({ path: file, clip, timeout: 120_000 })
    console.log(`SHOT ${file}`)
  }
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
