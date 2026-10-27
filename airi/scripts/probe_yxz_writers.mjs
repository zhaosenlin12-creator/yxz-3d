/**
 * Who is writing the bones.
 *
 * The figure has three possible writers on any given bone: the mixer
 * (the clips), the behaviour layer, and the rig itself (spring bones,
 * look-at, humanoid).  When a bone moves that should be held, the only
 * way to find out why is to stop the writers one at a time and see
 * which one the movement belongs to.
 *
 * This pauses the mixer, then pauses the behaviour layer, and reports
 * what each bone does under each condition.
 *
 * Usage:
 *   node scripts/probe_yxz_writers.mjs [baseUrl]
 */

import path from 'node:path'
import process from 'node:process'

import { readdirSync } from 'node:fs'
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

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 700 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

async function measure(query) {
  await page.goto(`${baseUrl}/yxz-avatar${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )

  return page.evaluate(async () => {
    const vrm = window.__yxzVrm
    const debug = window.__yxzDebug
    const bones = []
    vrm.scene.traverse((object) => {
      if (object.isBone)
        bones.push(object)
    })

    const quat = () => new vrm.scene.quaternion.constructor()
    const angleBetween = (a, b) => {
      const dot = Math.abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w)
      return 2 * Math.acos(Math.min(1, Math.max(-1, dot))) * 180 / Math.PI
    }

    const sample = async (label, seconds = 6) => {
      const first = new Map(bones.map(b => [b.name, b.quaternion.clone()]))
      const started = performance.now()
      while (performance.now() - started < seconds * 1000) {
        await new Promise(resolve => setTimeout(resolve, 120))
      }
      const rows = bones.map(bone => ({
        bone: bone.name,
        deg: +angleBetween(first.get(bone.name), bone.quaternion).toFixed(2),
      })).filter(row => row.deg > 0.05).sort((a, b) => b.deg - a.deg)
      return { label, rows }
    }

    const results = []
    // The mixer off: whatever still moves is the behaviour layer or the
    // rig itself.
    debug.freeze(true)
    results.push(await sample('mixer-frozen'))

    debug.freeze(false)
    results.push(await sample('mixer-running'))

    return {
      clip: debug.clip(),
      clipTime: debug.clipTime(),
      mixerTime: debug.mixerTime(),
      playing: debug.playing(),
      weight: debug.weight(),
      duration: debug.duration(),
      actionCount: debug.actionCount(),
      results,
    }
  })
}

const report = {
  normal: await measure(''),
  noLife: await measure('?noLife=1'),
}

console.log(JSON.stringify(report, null, 2))
if (pageErrors.length)
  console.log('pageErrors', pageErrors)
await browser.close()
