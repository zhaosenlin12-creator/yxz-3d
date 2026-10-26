/**
 * Render the character with no lighting at all.
 *
 * Everything else has been ruled out: the texture, the outline, the
 * shadows, the multisampling, the rim light, the terminator, the alpha
 * and the camera angle.  What is left is either the texture or the way
 * the geometry is shaded, and a plain unlit material tells them apart.
 *
 *   basic material, texture   the band is in the texture
 *   basic material, no texture  the band is in the geometry or the lights
 *
 * A normals material settles the second case: a band that shows up in the
 * normals is a rough surface, and a band that does not is a depth fight.
 *
 * Usage: node scripts/probe_yxz_band5.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-band5'
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

async function swapMaterial(mode) {
  await page.evaluate((mode) => {
    const three = window.__yxzDebug?.three
    if (!three)
      return
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh)
        return
      const previous = Array.isArray(object.material) ? object.material[0] : object.material
      if (mode === 'texture') {
        object.material = new three.MeshBasicMaterial({
          map: previous?.map ?? null,
          color: 0xFFFFFF,
          side: three.FrontSide,
          transparent: true,
        })
      }
      else if (mode === 'white') {
        object.material = new three.MeshBasicMaterial({
          color: 0xBBBBBB,
          side: three.FrontSide,
          transparent: true,
        })
      }
      else {
        object.material = new three.MeshNormalMaterial({
          side: three.FrontSide,
          transparent: true,
        })
      }
    })
  }, mode)
  await page.waitForTimeout(5000)
}

await park()
await shoot('1-as-is')

// The texture on its own, with no light and no shading.
await swapMaterial('texture')
await shoot('2-basic-texture')

// A flat white body, with no texture at all.
await swapMaterial('white')
await shoot('3-basic-white')

// The normals as colour.  A rough surface shows up here as noise; a
// depth fight does not, because the normals are the same either way.
await swapMaterial('normals')
await shoot('4-normals')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
