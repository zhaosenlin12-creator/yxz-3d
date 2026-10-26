/** The post stack, taken apart, to see which pass owns a defect.
 *
 * The character is drawn by a beauty pass and then run through a
 * silhouette pass and a bloom.  A fleck of ink on the chest can come
 * from the mesh (a hole in the shell) or from the silhouette pass (a
 * crack in the shell that the pass read as an edge), and the two look
 * the same in a capture.  Turning the passes off one at a time tells
 * them apart.
 *
 * Usage: node scripts/probe_yxz_post_ab.mjs [baseUrl] [outDir]
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

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-diag/post-ab'

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
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  const camera = window.__yxzDebug?.camera?.()
  if (camera) {
    camera.position.set(0.4, 3.4, 2.6)
    camera.lookAt(0, 2.9, 0.4)
    camera.updateProjectionMatrix()
  }
})
await page.waitForTimeout(2500)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')

await canvas.screenshot({ path: path.join(outDir, 'a-baseline.png') })
console.log('SHOT a-baseline')

await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(1500)
await canvas.screenshot({ path: path.join(outDir, 'b-no-outline.png') })
console.log('SHOT b-no-outline')

await page.evaluate(() => {
  const pass = window.__yxzDebug?.bloomPass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(1500)
await canvas.screenshot({ path: path.join(outDir, 'c-no-bloom.png') })
console.log('SHOT c-no-bloom')

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
