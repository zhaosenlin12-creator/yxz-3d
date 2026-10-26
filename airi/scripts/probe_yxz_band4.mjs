/**
 * Is the speckle band the multisample resolve?
 *
 * The visor has a thin dark gasket between the helmet lip and the navy
 * face.  Blender renders it as one clean dark line.  In three it comes
 * out as a wide dithered band, which is what a multisampled target does
 * to a sliver of geometry: every sample resolves its own depth, and the
 * samples that land on the lip and the samples that land on the visor
 * are averaged into a mix.  The band has to be as wide as the sliver is
 * deep, and the sliver is deep because the lip lies almost flat against
 * the visor.
 *
 * Turning the multisampling off makes the depth test pick one surface
 * per pixel, so the band should collapse into a single line.
 *
 * Usage: node scripts/probe_yxz_band4.mjs [baseUrl] [outDir]
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

async function importSharp() {
  const require = createRequire(import.meta.url)
  try {
    return require('sharp')
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).filter(e => e.startsWith('sharp@')).sort().at(-1)
  if (!match)
    return null
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  if (!existsSync(entry))
    return null
  return (await import(pathToFileURL(entry).href)).default
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
const outDir = process.argv[3] ?? 'docs/yxz-band4'
await mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')

async function park() {
  await page.evaluate(() => {
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  await page.waitForTimeout(6000)
}

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    const { width, height } = await sharp(file).metadata()
    await sharp(file)
      .extract({ left: Math.round(width * 0.30), top: Math.round(height * 0.18), width: Math.round(width * 0.42), height: Math.round(height * 0.22) })
      .resize({ width: 1400, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-band.png`))
  }
  console.log('SHOT', name)
}

await park()
await shoot('1-as-is')

const samples = await page.evaluate(() => {
  const composer = window.__yxzDebug?.composer?.()
  if (!composer)
    return null
  const before = composer.renderTarget1?.samples ?? null
  for (const target of [composer.renderTarget1, composer.renderTarget2]) {
    if (!target)
      continue
    target.samples = 0
    target.dispose()
  }
  return before
})
console.log('SAMPLES_BEFORE', samples)
await page.waitForTimeout(6000)
await shoot('2-no-msaa')

// And with the shadow map off on top of that, to be sure.
await page.evaluate(() => {
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer)
    renderer.shadowMap.enabled = false
})
await page.waitForTimeout(5000)
await shoot('3-no-msaa-no-shadow')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
