/** Sweep one MToon parameter against the running model.
 *
 * The wings are white feathers in the atlas and white feathers in a plain
 * render of the same file, and they reach the page as flat grey cards.
 * Nothing about the model changed between those two pictures, so the
 * difference is a term in the shader, and the only way to find which one
 * is to move it and look.  Each variant is applied to the live model and
 * shot from the same pose, so the pictures differ by one number.
 *
 * Usage:
 *   node scripts/probe_yxz_mtoon_ab.mjs [baseUrl] [outDir]
 *     [--param shadeColorFactor] [--values 1,1,1 0.7,0.75,0.9]
 */

import { mkdirSync } from 'node:fs'
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

import { readdirSync } from 'node:fs'

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(e => e.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

function flag(name, fallback) {
  return process.argv.includes(name)
    ? process.argv[process.argv.indexOf(name) + 1]
    : fallback
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = flag('--out', 'docs/yxz-diag/mtoon')
const param = flag('--param', 'shadeColorFactor')
const variants = flag('--values', '1,1,1 0.62,0.7,0.86').split(/\s+/)

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
for (const [index, raw] of variants.entries()) {
  const value = raw.includes(',')
    ? raw.split(',').map(Number)
    : Number(raw)
  const touched = await page.evaluate(
    ([name, setting]) => window.__yxzDebug?.setUniform?.(name, setting),
    [param, value],
  )
  await page.waitForTimeout(1200)
  const file = path.join(outDir, `${index}-${param}-${raw}.png`)
  await canvas.screenshot({ path: file })
  console.log(`VARIANT ${file} touched=${touched}`)
}
console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
