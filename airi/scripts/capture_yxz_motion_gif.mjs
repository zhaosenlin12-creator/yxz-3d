/**
 * Capture the YXZ avatar in motion, in two ways.
 *
 * `live-*.png` is the character playing on its own: nothing is frozen,
 * nothing is seeked, the clip just runs and the frames are photographed
 * as they come.  This is the honest one -- it shows the wing flap, the
 * halo sway and the head drift happening at the same time, and it is
 * the only way to see the head drift at all, because the head drift is
 * a behaviour-layer motion and not part of any clip.
 *
 * `cycle-*.png` is the authored idle cycle, seeked to sixteen exact
 * times across its 8.03 second length.  Seeking is what makes the
 * sequence evenly spaced, so the resulting GIF loops without a hitch.
 *
 * Usage:
 *   node scripts/capture_yxz_motion_gif.mjs [baseUrl] [outDir]
 */

import path from 'node:path'
import process from 'node:process'

import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}

  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
  const match = readdirSync(store)
    .filter(entry => entry.startsWith('playwright@'))
    .sort()
    .at(-1)
  if (!match)
    throw new Error('playwright is not installed')
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const outDir = process.argv[3] ?? '.tmp/yxz-motion'
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 880, height: 660 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/**
 * Read the joints that are supposed to move, plus a handful that are
 * supposed to stay put.  The second group is the interesting one: a
 * body joint that drifts by a fraction of a degree is the beginning of
 * the tearing, so it is worth proving it is at zero.
 */
function readBones() {
  return page.evaluate(() => {
    const vrm = window.__yxzVrm
    const wanted = ['wingL', 'wingR', 'halo', 'head', 'leftEye', 'rightEye', 'chest', 'neck', 'spine']
    const out = {}
    const euler = new vrm.scene.rotation.constructor()
    vrm.scene.traverse((object) => {
      if (!object.isBone || !wanted.includes(object.name))
        return
      euler.setFromQuaternion(object.quaternion, 'YXZ')
      out[object.name] = [
        +(euler.x * 180 / Math.PI).toFixed(2),
        +(euler.y * 180 / Math.PI).toFixed(2),
        +(euler.z * 180 / Math.PI).toFixed(2),
      ]
    })
    return out
  })
}

// A three-quarter view.  The wings are wide, so a dead-on camera
// flattens the flap into a change of shadow; from the side the arc of
// the wing tip is visible.
await page.evaluate(() => {
  const camera = window.__yxzDebug?.camera?.()
  if (!camera)
    return
  camera.position.set(3.6, 2.35, 7.9)
  camera.lookAt(0, 1.95, 0)
  camera.updateProjectionMatrix()
})

// ---- live pass -------------------------------------------------------
//
// The software renderer manages about a quarter of a frame a second, so
// the character's own clock is run faster than the wall clock.  Nothing
// is frozen: this is the character playing.
const live = []
await page.evaluate(() => window.__yxzDebug?.timeScale(4))
for (let index = 0; index < 12; index++) {
  await page.waitForTimeout(2600)
  const bones = await readBones()
  live.push({ index, bones })
  await canvas.screenshot({ path: `${outDir}/live-${String(index).padStart(2, '0')}.png` })
  console.log(`live ${index}`)
}
await page.evaluate(() => window.__yxzDebug?.timeScale(1))

// ---- authored cycle pass ---------------------------------------------
const duration = await page.evaluate(() => {
  const debug = window.__yxzDebug
  debug?.freeze(true)
  return debug?.snap?.('YXZ_Idle', 0) ?? 8.03
})

const CYCLE_FRAMES = 16
const cycle = []
for (let index = 0; index < CYCLE_FRAMES; index++) {
  const at = (duration * index) / CYCLE_FRAMES
  await page.evaluate(time => window.__yxzDebug?.snap?.('YXZ_Idle', time), at)
  await page.waitForTimeout(2400)
  const bones = await readBones()
  cycle.push({ at: +at.toFixed(2), bones })
  await canvas.screenshot({ path: `${outDir}/cycle-${String(index).padStart(2, '0')}.png` })
  console.log(`cycle ${index} t=${at.toFixed(2)}`)
}

writeFileSync(
  path.join(outDir, 'motion.json'),
  JSON.stringify({ duration, live, cycle, pageErrors }, null, 2),
)

console.log(`wrote ${outDir}`)
await browser.close()
