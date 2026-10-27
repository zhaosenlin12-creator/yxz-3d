/**
 * Screenshot the product pages and report which model is on the stage.
 *
 * Usage:
 *   node scripts/capture_yxz_pages.mjs [baseUrl] [outDir]
 */

import path from 'node:path'
import process from 'node:process'

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}

  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
  const match = readdirSync(store)
    .filter(entry => entry.startsWith('playwright@'))
    .sort()
    .at(-1)
  if (!match)
    throw new Error('playwright is not installed')
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const outDir = process.argv[3] ?? '.tmp/yxz-pages'
mkdirSync(outDir, { recursive: true })

const ROUTES = ['/', '/yxz-studio', '/yxz-avatar']

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})

const report = []
for (const route of ROUTES) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  const pageErrors = []
  const consoleErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error')
      consoleErrors.push(message.text())
  })

  await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  // A cold dev server re-optimises its dependencies on the first hit,
  // and the character is a 37 MB model on top of that, so the page can
  // sit blank for a while.  Wait for the canvas rather than for the
  // clock: a screenshot of a loading screen says nothing.
  await page.waitForSelector('.yxz-real-model-canvas canvas, .yxz-procedural-scene canvas, .yxz-canvas-frame canvas', { timeout: 180_000 })
  await page.waitForTimeout(12_000)

  const info = await page.evaluate(() => {
    const real = document.querySelector('.yxz-real-model-canvas canvas')
    const procedural = document.querySelector('.yxz-procedural-scene canvas')
    const canvases = Array.from(document.querySelectorAll('canvas')).map((canvas) => {
      const box = canvas.getBoundingClientRect()
      return {
        cls: canvas.parentElement?.className ?? canvas.className,
        css: [Math.round(box.width), Math.round(box.height)],
        buffer: [canvas.width, canvas.height],
      }
    })
    return {
      realModel: Boolean(real),
      procedural: Boolean(procedural),
      canvases,
    }
  })

  const name = route === '/' ? 'home' : route.replace(/\//g, '').replace(/^/, 'page-')
  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: false })
  report.push({ route, info, pageErrors, consoleErrors: consoleErrors.slice(0, 8) })
  console.log(`${route} -> ${JSON.stringify(info)}`)
  await page.close()
}

console.log(JSON.stringify(report, null, 2))
await browser.close()
