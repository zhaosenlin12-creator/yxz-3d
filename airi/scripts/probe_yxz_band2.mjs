/**
 * Last two candidates for the speckle band on the visor crease.
 *
 * The band survives the rim light being switched off and survives a
 * terminator that has been softened into a plain gradient, so it is not
 * the shading.  It is two surfaces at nearly the same depth, and this
 * measures the two ways to separate them:
 *
 *   a normal push   the two sheets of a crease face opposite ways, so
 *                   moving the vertices along their own normals pulls
 *                   them apart.  The smallest push that clears the band
 *                   is the number that matters, because a push also
 *                   fattens the silhouette
 *   a depth offset  `polygonOffset` pushes a fragment along the depth
 *                   axis, scaled by how steeply the surface faces away.
 *                   Two crossing sheets have different slopes, so a
 *                   large enough factor can separate them
 *
 * Usage: node scripts/probe_yxz_band2.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-band2'
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
      .extract({ left: Math.round(width * 0.36), top: Math.round(height * 0.215), width: Math.round(width * 0.3), height: Math.round(height * 0.06) })
      .resize({ width: 1400, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-band.png`))
  }
  console.log('SHOT', name)
}

// The body is one mesh and the face overlays are several, so the push has
// to skip the overlays: moving the eye geometry would take the eyes out
// of their sockets.
async function pushBody(distance) {
  await page.evaluate((distance) => {
    const body = window.__yxzVrm.scene.getObjectByName('tripo_mesh_886880fc-6cae-4d94-9577-31f0c6026a55')
      ?? window.__yxzVrm.scene.children.find(child => child.isMesh)
    if (!body)
      return
    const position = body.geometry?.attributes?.position
    const normal = body.geometry?.attributes?.normal
    if (!position || !normal)
      return
    for (let i = 0; i < position.count; i++) {
      position.setXYZ(
        i,
        position.getX(i) + normal.getX(i) * distance,
        position.getY(i) + normal.getY(i) * distance,
        position.getZ(i) + normal.getZ(i) * distance,
      )
    }
    position.needsUpdate = true
    body.geometry.computeBoundingSphere()
  }, distance)
  await page.waitForTimeout(4500)
}

async function setPolygonOffset(factor, units) {
  await page.evaluate(({ factor, units }) => {
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh)
        return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      for (const material of list) {
        if (!material)
          continue
        material.polygonOffset = factor > 0 || units > 0
        material.polygonOffsetFactor = factor
        material.polygonOffsetUnits = units
        material.needsUpdate = true
      }
    })
  }, { factor, units })
  await page.waitForTimeout(4500)
}

await park()
await shoot('1-as-is')

await pushBody(0.0005)
await shoot('2-push-0.0005')

await pushBody(0.001)
await shoot('3-push-0.001')

await pushBody(0.002)
await shoot('4-push-0.002')

await pushBody(0.005)
await shoot('5-push-0.005')

await setPolygonOffset(8, 16)
await shoot('6-polygon-offset')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
