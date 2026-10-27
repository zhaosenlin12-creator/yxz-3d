/**
 * The wing flap, frame by frame.
 *
 * The wings are the one movement in this figure that comes from the
 * model's own animation rather than from the motion layer, so they have
 * to be checked two ways: that the flap is actually visible from the
 * camera the visitor is looking at, and that the wing root -- where the
 * wing shares its geometry with the back -- does not tear when the
 * wing turns.
 *
 * The clip is parked on exact frames rather than sampled on wall-clock
 * time, because the headless renderer manages a fraction of a frame a
 * second and waiting for a pose to come round would take all day.
 *
 * Usage:
 *   node scripts/capture_yxz_wings.mjs [baseUrl] [outDir]
 */

import path from 'node:path'
import process from 'node:process'

import { mkdirSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
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

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

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
const outDir = process.argv[3] ?? '.tmp/yxz-wings'
mkdirSync(outDir, { recursive: true })

// The idle clip is 8.03 seconds long and the wing's own cycle sits inside
// it: the flap reaches its top at about 2.0 seconds, its bottom at about
// 6.8, and it is back where it started at 8.0.
const TIMES = [0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.9, 7.5]

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 760 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')
const readings = []

for (const at of TIMES) {
  const pose = await page.evaluate((time) => {
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', time)
    return null
  }, at)
  // Give the renderer a frame to pick the new pose up.
  await page.waitForTimeout(2600)

  const bones = await page.evaluate(() => {
    const vrm = window.__yxzVrm
    const out = {}
    const euler = new vrm.scene.rotation.constructor()
    for (const name of ['wingL', 'wingR', 'halo', 'head']) {
      let node = null
      vrm.scene.traverse((object) => {
        if (!node && object.isBone && object.name === name)
          node = object
      })
      if (!node)
        continue
      euler.setFromQuaternion(node.quaternion, 'YXZ')
      out[name] = {
        x: +(euler.x * 180 / Math.PI).toFixed(2),
        y: +(euler.y * 180 / Math.PI).toFixed(2),
        z: +(euler.z * 180 / Math.PI).toFixed(2),
        world: node.getWorldPosition(new vrm.scene.position.constructor()).toArray().map(v => +v.toFixed(3)),
      }
    }
    return out
  })
  readings.push({ at, bones, pose })

  await canvas.screenshot({ path: `${outDir}/flap-${String(at).replace('.', '_')}.png` })
  console.log(`captured t=${at}`)
}

// The back, where the wings meet the body.  The camera is in front, so
// the wing root has to be seen from behind to be judged at all.
await page.evaluate(() => {
  const camera = window.__yxzDebug?.camera?.()
  if (!camera)
    return
  camera.position.set(0, 2.4, -8.8)
  camera.lookAt(0, 2.05, 0)
  camera.updateProjectionMatrix()
})
for (const at of [0, 2.0, 6.9]) {
  await page.evaluate((time) => {
    window.__yxzDebug?.snap?.('YXZ_Idle', time)
  }, at)
  await page.waitForTimeout(2600)
  await canvas.screenshot({ path: `${outDir}/back-${String(at).replace('.', '_')}.png` })
  console.log(`captured back t=${at}`)
}

console.log(JSON.stringify({ readings, pageErrors }, null, 2))
await browser.close()
