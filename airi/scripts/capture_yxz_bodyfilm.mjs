/**
 * Film the whole figure while it stands, and tile the frames.
 *
 * The head film answers "is the head still"; this one answers "is the
 * figure one piece".  A head that drifts over a body that stands there
 * is a puppet with a face on it, and no single frame shows that -- it
 * takes a row of frames, where the body either goes with the head or
 * does not.
 *
 * Usage:
 *   node scripts/capture_yxz_bodyfilm.mjs [baseUrl] [outDir] [--frames 12] [--gap 1.6]
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
  return at < 0 ? fallback : Number(args[at + 1])
}
const positional = args.filter((token, index) => !token.startsWith('--') && !(index > 0 && args[index - 1].startsWith('--')))
const baseUrl = positional[0] ?? 'http://127.0.0.1:5199'
const outDir = positional[1] ?? 'docs/yxz-audit/bodyfilm'
const frameCount = flag('frames', 12)
const gap = flag('gap', 1.6)

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
// Let the greeting finish and the figure settle.
await page.waitForTimeout(14_000)

const canvas = page.locator('canvas').first()
const frames = []
const times = []
const poses = []
for (let i = 0; i < frameCount; i++) {
  if (i)
    await page.waitForTimeout(gap * 1000)
  const file = path.join(outDir, `frame-${String(i).padStart(3, '0')}.png`)
  await canvas.screenshot({ path: file })
  const state = await page.evaluate(() => ({
    modelTime: window.__yxzDebug.motionTime(),
    clip: window.__yxzDebug.clip(),
    oneShot: window.__yxzDebug.oneShotPlaying(),
  }))
  times.push(state.modelTime)
  poses.push(state)
  frames.push(file)
  console.log(`captured ${file}  model ${state.modelTime.toFixed(1)}s  clip ${state.clip}${state.oneShot ? ` + ${state.oneShot}` : ''}`)
}
await writeFile(path.join(outDir, 'timing.json'), JSON.stringify({ times, poses }, null, 2))
await browser.close()

const sheet = await chromium.launch({ executablePath: installedChromium() })
const sheetPage = await sheet.newPage({ viewport: { width: 1400, height: 1400 } })
const columns = 6
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
        <figcaption>${times[index].toFixed(1)}s</figcaption>
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
