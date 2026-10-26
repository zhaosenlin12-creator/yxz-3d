/**
 * Find where the white speckle around the visor comes from.
 *
 * The speckle looks like it sits on the dark visor right where the helmet
 * shell crosses it, but "looks like" is not a cause.  Four different
 * sources could produce it:
 *
 *   the texture      the baked base colour is noisy in that area
 *   the normal map   a noisy normal map makes the cel terminator flicker
 *   the geometry     a thin interior shell of the scan pokes through
 *   the outline      the silhouette pass smears the alpha edge
 *
 * Each variant turns exactly one of them off, so a single screenshot
 * settles it.  The mesh-id variant paints every mesh a different hue, which
 * shows which surface actually owns the speckled pixels.
 *
 * Usage: node scripts/probe_yxz_face.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-face'
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

// The mesh inventory decides whether a "thin interior shell" is even
// possible, so it is worth printing before anything else.
const inventory = await page.evaluate(() => {
  const rows = []
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const geometry = object.geometry
    const position = geometry?.attributes?.position
    const index = geometry?.index
    const list = Array.isArray(object.material) ? object.material : [object.material]
    rows.push({
      name: object.name,
      vertices: position?.count ?? 0,
      triangles: index ? index.count / 3 : (position?.count ?? 0) / 3,
      materials: list.map(m => m?.type).join('|'),
      hasMap: list.some(m => Boolean(m?.map)),
      hasNormalMap: list.some(m => Boolean(m?.normalMap)),
      transparent: list.some(m => Boolean(m?.transparent)),
      alphaTest: list.map(m => m?.alphaTest ?? 0).join('|'),
      side: list.map(m => m?.side).join('|'),
    })
  })
  return rows
})
console.log('MESHES', JSON.stringify(inventory, null, 2))

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
    // A tight crop on the visor: that is where the speckle lives.
    await sharp(file)
      .extract({
        left: Math.round(width * 0.31),
        top: Math.round(height * 0.20),
        width: Math.round(width * 0.38),
        height: Math.round(height * 0.26),
      })
      .resize({ width: 1000, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-face.png`))
  }
  console.log('SHOT', name)
}

async function patchMaterials(patch) {
  await page.evaluate((patch) => {
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh)
        return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      for (const material of list) {
        if (!material)
          continue
        for (const [key, value] of Object.entries(patch)) {
          if (value === null) {
            material[key] = null
            continue
          }
          const target = material[key] ?? material.uniforms?.[key]?.value
          if (!target)
            continue
          if (target.isColor)
            target.set(value)
          else if (target.set)
            target.set(value)
          else
            material[key] = value
        }
      }
    })
  }, patch)
}

await park()
await shoot('1-as-is')

// The silhouette pass paints ink where the alpha ring is wider than the
// centre, so a soft alpha edge turns into a smudge.  Turning the pass off
// says whether the speckle belongs to it.
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(4000)
await shoot('2-no-outline')
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = true
})
await page.waitForTimeout(2000)

// The baked base colour.
await patchMaterials({ map: null })
await page.waitForTimeout(4000)
await shoot('3-no-map')

// The normal map.  A noisy normal turns a cel terminator into dither.
await patchMaterials({ normalMap: null })
await page.waitForTimeout(4000)
await shoot('4-no-map-no-normal')

// A per-mesh hue, with every texture gone, so the geometry alone decides
// which surface owns the speckled pixels.
await page.evaluate(() => {
  let index = 0
  const palette = [0xE4573D, 0x3D8FE4, 0x57C77A, 0xE0A93B, 0x9B59D0, 0x1FB6C4, 0xE06BB0, 0x7F8C9B]
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      if (!material?.color)
        continue
      material.color.setHex(palette[index % palette.length])
      material.emissive?.setHex(0x000000)
    }
    index += 1
  })
})
await page.waitForTimeout(4000)
await shoot('5-mesh-id')

// Restore, then look at the coverage channel on its own: if the silhouette
// is ragged, the alpha buffer is the problem.
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await park()
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(4000)
await shoot('6-no-outline-clean')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
