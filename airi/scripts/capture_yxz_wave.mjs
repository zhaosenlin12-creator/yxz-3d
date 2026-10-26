/**
 * Film the authored one-shot clips.
 *
 * The behaviour layer can only be judged from a contact sheet, and so can
 * these: a wave that is a wave has the forearm swinging and the rest of
 * the figure standing still, and a wave that is broken has the whole
 * body moving with it.  One frame cannot tell those apart.
 *
 * The clip is parked on exact times with the mixer's own `setTime`, and
 * the render loop is frozen so that the pose does not drift while the
 * screenshot is being taken -- at four frames a second, a two second
 * wait is eight frames of movement.
 *
 * Usage:
 *   node scripts/capture_yxz_wave.mjs [baseUrl] [outDir] [--clip YXZ_Wave]
 */

import { mkdir, writeFile } from 'node:fs/promises'
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
  return at < 0 ? fallback : args[at + 1]
}
const positional = args.filter((token, index) => !token.startsWith('--') && !(index > 0 && args[index - 1].startsWith('--')))
const baseUrl = positional[0] ?? 'http://127.0.0.1:5199'
const outDir = positional[1] ?? 'docs/yxz-audit/wave'
const clipName = flag('clip', 'YXZ_Wave')

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
await mkdir(outDir, { recursive: true })

const browser = await chromium.launch({
  executablePath: installedChromium(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(() => !!window.__yxzDebug, null, { timeout: 120_000 })
// Let the figure settle into its idle before the film starts.
await page.waitForTimeout(8000)

const duration = await page.evaluate(name => {
  const debug = window.__yxzDebug
  debug.freeze(true)
  const snapped = debug.snap(name, 0)
  return snapped
}, clipName)
if (!duration)
  throw new Error(`clip ${clipName} is not in the model`)

const canvas = page.locator('canvas').first()
const box = await canvas.boundingBox()
if (!box)
  throw new Error('canvas has no box')

// The whole figure.  A wave is an arm movement and an arm is at the
// bottom of the picture, so a crop of the head cannot show one.
const cropW = Math.round(box.width)
const cropH = Math.round(box.height)
const cropX = Math.round(box.x)
const cropY = Math.round(box.y)

const frames = []
const times = []
const steps = 10
for (let i = 0; i < steps; i++) {
  const time = (duration * i) / (steps - 1)
  await page.evaluate(([name, at]) => {
    window.__yxzDebug.snap(name, at)
  }, [clipName, time])
  await page.waitForTimeout(900)
  const file = path.join(outDir, `frame-${String(i).padStart(3, '0')}.png`)
  await page.screenshot({ path: file, clip: { x: cropX, y: cropY, width: cropW, height: cropH } })
  times.push(time)
  frames.push(file)
  console.log(`captured ${file}  clip ${time.toFixed(2)}s`)
}
await writeFile(path.join(outDir, 'timing.json'), JSON.stringify({ clip: clipName, duration, times }, null, 2))
await browser.close()

const sheet = await chromium.launch({ executablePath: installedChromium() })
const sheetPage = await sheet.newPage({ viewport: { width: 1200, height: 1200 } })
const columns = 5
const sheetHtml = path.join(outDir, 'sheet.html')
await writeFile(sheetHtml, `
  <style>
    body { margin: 0; background: #101014; font: 12px/1.4 ui-monospace, monospace; color: #8a8a95; }
    .sheet { display: grid; grid-template-columns: repeat(${columns}, 1fr); gap: 2px; }
    figure { margin: 0; position: relative; }
    img { display: block; width: 100%; }
    figcaption { position: absolute; left: 4px; top: 4px; background: #101014cc; padding: 1px 4px; }
  </style>
  <div class="sheet">
    ${frames.map((file, index) => `
      <figure>
        <img src="${path.basename(file)}">
        <figcaption>${times[index].toFixed(2)}s</figcaption>
      </figure>`).join('')}
  </div>
`)
await sheetPage.goto(pathToFileURL(sheetHtml).href, { waitUntil: 'networkidle' })
await sheetPage.waitForLoadState('networkidle')
const outFile = path.join(outDir, 'contact-sheet.png')
await sheetPage.screenshot({ path: outFile, fullPage: true })
await sheet.close()
console.log(`sheet ${outFile}`)
if (errors.length)
  console.log(`pageErrors: ${JSON.stringify(errors)}`)
