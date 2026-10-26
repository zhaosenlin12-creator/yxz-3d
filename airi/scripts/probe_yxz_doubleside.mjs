/** Is the shattered look the surface that is thrown away, or the surface
 * that is missing?
 *
 * Two faults look the same on screen and need opposite repairs.  A hole in
 * the shell is a place there is no surface, and the only fix is to grow
 * one.  A face wound the wrong way round is a surface that is there and is
 * simply not drawn, and the fix is one boolean.  They are told apart by
 * letting the renderer draw both sides: a hole stays a hole, because there
 * is nothing behind it to draw, while a patch that fills in was there all
 * along and was being culled.
 *
 * Usage: node scripts/probe_yxz_doubleside.mjs [baseUrl] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
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
const outDir = process.argv[3] ?? 'docs/yxz-diag/side'

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({
  viewport: { width: 1040, height: 900 },
  deviceScaleFactor: 1,
})
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
})
await page.waitForTimeout(2000)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')
await canvas.screenshot({ path: path.join(outDir, 'front.png') })

const flipped = await page.evaluate(() => {
  const seen = window.__yxzDebug
  if (!seen?.setSide)
    return -1
  return seen.setSide(2)
})
await page.waitForTimeout(1500)
await canvas.screenshot({ path: path.join(outDir, 'double.png') })
console.log(`SIDESET ${flipped} errors=${JSON.stringify(errors)}`)
await browser.close()
