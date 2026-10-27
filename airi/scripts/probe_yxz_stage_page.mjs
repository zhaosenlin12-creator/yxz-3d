/**
 * Which model is actually on the product stage?
 *
 * The stage renders the real VRM, and falls back to a procedural figure
 * if the real one fails to load.  The fallback is silent, so a page can
 * look like it is showing the good model while showing the stand-in
 * instead.  This probe reports which of the two is in the DOM, and
 * prints every error the page logged.
 *
 * Usage:
 *   node scripts/probe_yxz_stage_page.mjs [baseUrl] [path]
 */

import path from 'node:path'
import process from 'node:process'

import { existsSync, readdirSync } from 'node:fs'
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
const route = process.argv[3] ?? '/'
const pageUrl = `${baseUrl}${route}`

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const consoleErrors = []
const pageErrors = []
page.on('console', (message) => {
  if (message.type() === 'error')
    consoleErrors.push(message.text())
})
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 })

// Give the 37 MB VRM time to come over the wire and to be parsed.
let state = null
for (let attempt = 0; attempt < 60; attempt++) {
  await page.waitForTimeout(2000)
  state = await page.evaluate(() => {
    const real = document.querySelector('.yxz-real-model-canvas canvas')
    const procedural = document.querySelector('.yxz-procedural-scene canvas')
    const image = document.querySelector('.yxz-image-scene canvas, img[src*="yxz"]')
    const settings = JSON.parse(localStorage.getItem('airi:settings:stage-model') ?? 'null')
    return {
      realModel: Boolean(real),
      procedural: Boolean(procedural),
      imageScene: Boolean(image),
      realCanvasSize: real ? [real.width, real.height] : null,
      stageModelSelected: settings?.stageModelSelected ?? null,
      bodyText: (document.body.innerText ?? '').slice(0, 400),
    }
  })
  if (state.realModel || state.procedural || state.imageScene)
    break
}

console.log(JSON.stringify({ pageUrl, state, pageErrors, consoleErrors: consoleErrors.slice(0, 30) }, null, 2))
await browser.close()
