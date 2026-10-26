/**
 * Paint every mesh a different colour and look at the result.
 *
 * The character is a merge of a couple of hundred separate sheets, and the
 * seams between them are what reads as "shattered": the dark visor cuts
 * into the white face in a row of teeth, a torn scratch crosses the side of
 * the helmet, the halo above the head is a broken arc.  Guessing which
 * sheet causes which is hopeless, so this probe gives every mesh its own
 * flat colour and photographs the result.
 *
 * The colour is read straight out of the framebuffer, so tone mapping and
 * the colour-space conversion are both switched off for the shot: the
 * pixel is then exactly the colour that was written into the material.
 *
 * Usage: node scripts/probe_yxz_id.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-id'
await mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 })

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
await page.waitForTimeout(6000)

const canvas = page.locator('.yxz-real-model-canvas canvas')

// A palette that stays apart after the framebuffer is quantised, and that
// still reads apart to the eye.
const PALETTE = [
  0xE6194B, 0x3CB44B, 0xFFE119, 0x4363D8,
  0xF58231, 0x911EB4, 0x46F0F0, 0xF032E6,
  0xBCF60C, 0xFABEBE, 0x008080, 0xE1BE6A,
  0x9A6324, 0x800000, 0xAAFFC3, 0x808000,
]

const inventory = await page.evaluate((palette) => {
  const three = window.__yxzDebug?.three
  const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
  const renderer = window.__yxzDebug?.renderer?.()
  if (!three || !scene || !renderer)
    return null

  // Straight to the framebuffer: no tone mapping, no colour conversion.
  renderer.toneMapping = three.NoToneMapping
  renderer.outputColorSpace = three.LinearSRGBColorSpace
  window.__yxzDebug?.outlinePass?.() && (window.__yxzDebug.outlinePass().enabled = false)

  const meshes = []
  scene.traverse((object) => {
    if (object.isMesh)
      meshes.push(object)
  })

  meshes.forEach((object, index) => {
    const colour = palette[index % palette.length]
    object.material = new three.MeshBasicMaterial({
      color: colour,
      side: three.DoubleSide,
      transparent: false,
      depthWrite: true,
    })
  })

  return meshes.map((object, index) => ({
    index,
    name: object.name || '(unnamed)',
    colour: `#${palette[index % palette.length].toString(16).padStart(6, '0')}`,
    vertices: object.geometry?.attributes?.position?.count ?? 0,
    triangles: (object.geometry?.index?.count ?? object.geometry?.attributes?.position?.count ?? 0) / 3,
  }))
}, PALETTE)

console.log(JSON.stringify(inventory, null, 1))

await page.waitForTimeout(3000)
const file = path.join(outDir, 'id-full.png')
await canvas.screenshot({ path: file })

if (sharp) {
  await sharp(file)
    .extract({ left: 360, top: 230, width: 400, height: 280 })
    .resize({ width: 1200, kernel: 'nearest' })
    .toFile(path.join(outDir, 'id-face.png'))
  await sharp(file)
    .extract({ left: 380, top: 60, width: 300, height: 180 })
    .resize({ width: 1200, kernel: 'nearest' })
    .toFile(path.join(outDir, 'id-halo.png'))
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
