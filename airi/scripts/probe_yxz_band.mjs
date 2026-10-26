/**
 * Pin down what the fine speckle along the visor crease is made of.
 *
 * At ten times magnification the band is an irregular, high frequency
 * grain in a pale blue grey, and it sits exactly where the helmet curves
 * into the visor.  Three things happen on a crease like that, and each
 * one is switched off on its own here:
 *
 *   the rim light     MToon's parametric rim is a fresnel term, so on a
 *                     crease the normal swings wildly and the rim
 *                     highlight breaks into speckle
 *   the cel terminator a hard terminator over noisy scan normals is
 *                     another way to break the same crease into speckle
 *   the normals       if the grain is in the normals themselves, flat
 *                     shading will make the crease faceted but not grainy
 *
 * Usage: node scripts/probe_yxz_band.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-band'
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
    // The band sits on the top edge of the visor.
    await sharp(file)
      .extract({ left: Math.round(width * 0.36), top: Math.round(height * 0.215), width: Math.round(width * 0.3), height: Math.round(height * 0.06) })
      .resize({ width: 1400, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-band.png`))
  }
  console.log('SHOT', name)
}

async function patch(body) {
  await page.evaluate((body) => {
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh)
        return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      for (const material of list) {
        if (!material)
          continue
        for (const [key, value] of Object.entries(body)) {
          if (value === null) {
            material[key] = null
            continue
          }
          if (key === 'flatShading') {
            material.flatShading = value
            material.needsUpdate = true
            continue
          }
          const target = material[key] ?? material.uniforms?.[key]?.value
          if (!target)
            continue
          if (target.isColor)
            target.setRGB(value[0], value[1], value[2])
          else if (typeof target.set === 'function')
            target.set(value)
          else
            material[key] = value
        }
      }
    })
  }, body)
  await page.waitForTimeout(4500)
}

await park()
await shoot('1-as-is')

// The rim light on its own.
await patch({ parametricRimColorFactor: [0, 0, 0] })
await shoot('2-rim-off')

// The rim light back, but the terminator softened into a plain gradient.
await patch({ parametricRimColorFactor: [0.55, 0.70, 0.92], shadingToonyFactor: 1.0 })
await shoot('3-toony-1')

// Both off, so what is left is the diffuse term alone.
await patch({ shadingToonyFactor: 1.0 })
await shoot('4-rim-off-toony-1')

// The normals themselves, shown as flat facets.
await patch({ parametricRimColorFactor: [0.55, 0.70, 0.92], shadingToonyFactor: 0.22, flatShading: true })
await shoot('5-flat-shading')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()

