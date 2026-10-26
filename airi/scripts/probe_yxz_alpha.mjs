/**Read the beauty pass under the stage, and the same picture without the outline.
 *
 * The silhouette outline is drawn from the alpha of the beauty pass: a
 * pixel the character does not cover is a pixel the ink goes into.  That
 * makes the outline sensitive to the alpha the character is drawn with,
 * and when a part of the model arrives on screen paler than the rest --
 * a leg the page shows through -- the question is whether the model is
 * translucent there or the outline is throwing it away.
 *
 * Two readings answer it.  The first is the picture with the outline pass
 * switched off, which is the beauty pass as it stands.  The second is the
 * alpha channel of that same pass, read back off the GPU, at named
 * pixels.  A pixel that is opaque in the beauty pass and gone in the
 * finished picture belongs to the outline; a pixel that is already
 * translucent belongs to the model.
 *
 * Usage: node scripts/probe_yxz_alpha.mjs [baseUrl] [out.png] [x,y ...]
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

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const out = process.argv[3] ?? 'docs/yxz-diag/no-outline.png'
const points = process.argv.slice(4).map((pair) => {
  const [x, y] = pair.split(',').map(Number)
  return { x, y }
})

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const report = await page.evaluate((wanted) => {
  const debug = window.__yxzDebug
  const renderer = debug.renderer()
  const composer = debug.composer()
  const pass = debug.outlinePass()
  const canvas = renderer.domElement

  // The beauty pass is the buffer the outline reads.  Reading it back
  // needs the composer to have run at least once with the outline on, so
  // the read happens before the pass is switched off.
  const readBuffer = composer.readBuffer ?? composer.renderTarget1
  const size = new debug.three.Vector2()
  renderer.getSize(size)

  const rows = []
  for (const point of wanted) {
    const x = Math.round(point.x * (size.x / canvas.clientWidth))
    const y = Math.round((1 - point.y / canvas.clientHeight) * (size.y / canvas.clientHeight))
    const buffer = new Uint8Array(4)
    try {
      renderer.readRenderTargetPixels(readBuffer, x, y, 1, 1, buffer)
      rows.push({ point, buffer: Array.from(buffer) })
    }
    catch (error) {
      rows.push({ point, error: String(error) })
    }
  }

  if (pass) pass.enabled = false
  return { rows, size: [size.x, size.y], client: [canvas.clientWidth, canvas.clientHeight] }
}, points)

await page.waitForTimeout(2500)
await page.locator('.yxz-real-model-canvas canvas').screenshot({ path: out })

console.log(`ALPHA ${JSON.stringify(report)}`)
console.log(`SHOT ${out} errors=${JSON.stringify(errors)}`)
await browser.close()
