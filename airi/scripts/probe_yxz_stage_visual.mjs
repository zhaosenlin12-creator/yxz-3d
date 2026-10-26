/**
 * Inspect the YXZ avatar as the main chat stage actually renders it.
 *
 * The QA page and the stage are the same component but not the same pixels:
 * the stage draws the character larger, at a different device pixel ratio and
 * inside a differently sized canvas, and the silhouette outline is resolution
 * dependent.  Judging the outline from the QA page alone hides that, so this
 * measures the stage's real canvas and captures it.
 *
 * Usage: node scripts/probe_yxz_stage_visual.mjs [baseUrl] [outDir]
 */

import { mkdir } from 'node:fs/promises'
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
const outDir = process.argv[3] ?? 'docs/yxz-stage-visual'
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })

const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForSelector('canvas', { timeout: 180_000 })
// The stage mounts the 3D scene behind an intro animation; give the model time
// to finish its 14MB load before measuring anything.
await page.waitForTimeout(45_000)

const canvases = await page.evaluate(() => {
  return [...document.querySelectorAll('canvas')].map((canvas) => {
    const rect = canvas.getBoundingClientRect()
    return {
      className: canvas.className,
      width: canvas.width,
      height: canvas.height,
      cssWidth: Math.round(rect.width),
      cssHeight: Math.round(rect.height),
      devicePixelRatio: window.devicePixelRatio,
    }
  })
})
console.log('CANVASES', JSON.stringify(canvases, null, 2))

// The biggest canvas is the character stage.
const target = canvases.filter(c => c.width * c.height > 0)
  .sort((a, b) => (b.width * b.height) - (a.width * a.height))[0]
console.log('TARGET', JSON.stringify(target))

await page.screenshot({ path: `${outDir}/stage-full.png`, fullPage: false })
if (target) {
  const handles = await page.$$('canvas')
  for (const handle of handles) {
    const size = await handle.evaluate(c => ({ w: c.width, h: c.height }))
    if (size.w === target.width && size.h === target.height)
      await handle.screenshot({ path: `${outDir}/stage-canvas.png` })
  }
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
