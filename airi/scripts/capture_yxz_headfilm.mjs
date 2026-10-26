/**
 * Film the YXZ avatar in a real browser and tile the frames into one
 * contact sheet.
 *
 * The tables the motion probe prints answer "how far does the head
 * travel"; they do not answer "does it read as a person standing".  A
 * contact sheet does: a jitter shows up as a row of frames where the
 * face is a slightly different angle every time, and a sway shows up as
 * a row of frames where the face drifts slowly and comes back.
 *
 * The head is cropped tight, because that is the part the complaint is
 * about and because a full-body crop is too small to read an angle of
 * two degrees from.
 *
 * Usage:
 *   node scripts/capture_yxz_headfilm.mjs [baseUrl] [outDir] [--frames 24] [--gap 2.5]
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
const outDir = positional[1] ?? 'docs/yxz-audit/headfilm'
const frameCount = flag('frames', 24)
const gap = flag('gap', 2.5)

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
await mkdir(outDir, { recursive: true })

const browser = await chromium.launch({ executablePath: installedChromium() })
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded' })
await page.waitForFunction(
  () => document.body?.innerText?.includes('挂载') || !!document.querySelector('canvas'),
  null,
  { timeout: 120_000 },
)
// Let the figure settle into its idle before the film starts, so the
// first frame is not a pose it was still arriving at.
await page.waitForTimeout(12_000)

const canvas = page.locator('canvas').first()
const box = await canvas.boundingBox()
if (!box)
  throw new Error('canvas has no box')

// A tight crop on the head: the top of the helmet down to the chin.  The
// canvas carries a lot of empty sky around the figure, so the head is
// a small part of it and a generous crop shows the whole body, which
// is no use for judging an angle of two degrees.
const cropW = Math.round(box.width * 0.34)
const cropH = Math.round(box.height * 0.28)
const cropX = Math.round(box.x + (box.width - cropW) / 2)
const cropY = Math.round(box.y + box.height * 0.10)

const frames = []
const times = []
const clockStart = await page.evaluate(() => window.__yxzDebug.motionTime())
for (let i = 0; i < frameCount; i++) {
  if (i)
    await page.waitForTimeout(gap * 1000)
  const file = path.join(outDir, `frame-${String(i).padStart(3, '0')}.png`)
  await page.screenshot({ path: file, clip: { x: cropX, y: cropY, width: cropW, height: cropH } })
  times.push(await page.evaluate(() => window.__yxzDebug.motionTime()) - clockStart)
  frames.push(file)
  console.log(`captured ${file}`)
}
await writeFile(path.join(outDir, 'timing.json'), JSON.stringify({ nominalGap: gap, modelSeconds: times }, null, 2))
await browser.close()

// The contact sheet is drawn in the browser as well, so the script needs
// no image library.
const sheet = await chromium.launch({ executablePath: installedChromium() })
const sheetPage = await sheet.newPage({ viewport: { width: 1200, height: 1200 } })
const columns = 6
// The page is written next to the frames and opened from there, so the
// images resolve as relative paths.  A page built with `setContent` has
// no base URL of its own and every one of them comes back broken.
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
        <figcaption>${times[index].toFixed(1)}s model</figcaption>
      </figure>`).join('')}
  </div>
`)
await sheetPage.goto(pathToFileURL(sheetHtml).href, { waitUntil: 'networkidle' })
await sheetPage.waitForLoadState('networkidle')
const outFile = path.join(outDir, 'contact-sheet.png')
await sheetPage.screenshot({ path: outFile, fullPage: true })
await sheet.close()
console.log(`sheet ${outFile}`)
