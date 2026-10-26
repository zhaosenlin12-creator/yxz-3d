/** A/B the silhouette outline on the running model.
 *
 * The outline is drawn by dilating the beauty pass' alpha and inking the
 * difference.  That dilation finds *every* alpha blob, not just the
 * character's outer edge, so a piece of torn shell smaller than the line
 * width is inked solid and the crown of the head comes out as a field of
 * black dots.  This probe turns the pass off and on so the two can be
 * compared on the same pose.
 *
 * Usage: node scripts/probe_yxz_outline.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-diag/outline'

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1040, height: 900 }, deviceScaleFactor: 1 })
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
await page.waitForTimeout(2200)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')

for (const [name, enabled, erode] of [
  ['outline-plain', true, 0],
  ['outline-eroded', true, 1],
  ['outline-off', false, 1],
]) {
  const state = await page.evaluate(([value, depth]) => {
    const pass = window.__yxzDebug?.outlinePass?.()
    if (!pass)
      return 'no-pass'
    pass.enabled = value
    if (pass.uniforms?.uErode)
      pass.uniforms.uErode.value = depth
    return `enabled=${pass.enabled} erode=${pass.uniforms?.uErode?.value}`
  }, [enabled, erode])
  await page.waitForTimeout(1200)
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file} ${state}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
