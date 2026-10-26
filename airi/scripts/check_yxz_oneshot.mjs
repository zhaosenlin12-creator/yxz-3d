/**
 * Watch the live page for an authored gesture firing on its own.
 *
 * The gesture has to be scheduled by the character and not by the test,
 * so this waits for the scheduler to do it and reports what it saw.  The
 * model's own clock is run faster than the wall clock, because a browser
 * with a software rasteriser draws four frames a second and the whole
 * point of the check is the timing.
 *
 * Usage: node scripts/check_yxz_oneshot.mjs [baseUrl] [--scale 8] [--seconds 90]
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
  const match = readdirSync(store).filter(entry => entry.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function installedChromium() {
  const root = path.join(process.env.LOCALAPPDATA ?? '', 'ms-playwright')
  if (!existsSync(root))
    return undefined
  return readdirSync(root)
    .filter(entry => /^chromium-\d+$/.test(entry))
    .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))
    .map(entry => path.join(root, entry, 'chrome-win64', 'chrome.exe'))
    .find(existsSync)
}

const args = process.argv.slice(2)
function flag(name, fallback) {
  const at = args.indexOf(`--${name}`)
  return at < 0 ? fallback : Number(args[at + 1])
}
const baseUrl = args.find(token => !token.startsWith('--') && token.startsWith('http')) ?? 'http://127.0.0.1:5199'
const scale = flag('scale', 8)
const seconds = flag('seconds', 90)

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: installedChromium(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(() => !!window.__yxzDebug, null, { timeout: 120_000 })
await page.waitForTimeout(3000)
await page.evaluate(value => window.__yxzDebug.timeScale(value), scale)

const seen = []
const started = Date.now()
let fired = null
while ((Date.now() - started) / 1000 < seconds) {
  const state = await page.evaluate(() => ({
    clip: window.__yxzDebug.clip(),
    oneShot: window.__yxzDebug.oneShotPlaying(),
    modelTime: window.__yxzDebug.motionTime(),
    frames: window.__yxzDebug.frames(),
  }))
  if (state.oneShot && !fired) {
    fired = state
    console.log(`one-shot started: ${state.oneShot} at model time ${state.modelTime.toFixed(1)}s`)
  }
  const key = `${state.clip}|${state.oneShot}`
  if (seen.at(-1)?.key !== key) {
    seen.push({ key, ...state })
    console.log(`t=${((Date.now() - started) / 1000).toFixed(1)}s model=${state.modelTime.toFixed(1)}s clip=${state.clip} oneShot=${state.oneShot || '-'}`)
  }
  if (fired && !state.oneShot) {
    console.log(`one-shot finished, back on ${state.clip}`)
    break
  }
  await page.waitForTimeout(400)
}

console.log(JSON.stringify({ fired, transitions: seen.length, pageErrors: errors }, null, 2))
await browser.close()
if (!fired)
  process.exitCode = 1
