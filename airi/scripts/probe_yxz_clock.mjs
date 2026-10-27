/**
 * Is the mixer actually running?
 *
 * The bone report says the figure is nearly still, and the reason has
 * to be found before anything can be changed: a clip that is playing at
 * zero weight is not playing at all, and every measurement taken on
 * top of it is a measurement of nothing.
 *
 * This prints the mixer's own clock, the active action's weight and
 * time, and the character's clock, once a second, so the answer is a
 * number rather than an inference.
 *
 * Usage:
 *   node scripts/probe_yxz_clock.mjs [baseUrl] [seconds]
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
const seconds = Number(process.argv[3] ?? 12)
const timeScale = Number(process.argv[4] ?? 1)

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 700 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(async ({ seconds, timeScale }) => {
  const debug = window.__yxzDebug
  debug.timeScale(timeScale)
  const rows = []
  const started = performance.now()
  while (performance.now() - started < seconds * 1000) {
    rows.push({
      wall: +((performance.now() - started) / 1000).toFixed(2),
      mixerTime: debug.mixerTime(),
      clipTime: debug.clipTime(),
      weight: debug.weight(),
      playing: debug.playing(),
      characterTime: debug.motionTime(),
      clip: debug.clip(),
      attention: debug.attention?.() ?? null,
    })
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  return { rows, debugKeys: Object.keys(debug) }
}, { seconds, timeScale })

console.log(JSON.stringify(report, null, 2))
if (pageErrors.length)
  console.log('pageErrors', pageErrors)
await browser.close()
