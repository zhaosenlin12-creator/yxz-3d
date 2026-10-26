/**
 * Second pass on the visor speckle.
 *
 * The first probe ruled out the base colour texture and the silhouette
 * pass: the grain survives both.  Two causes are left, and they need
 * different fixes, so they are separated here.
 *
 *   shadow acne     the surface grazes the key light, so the shadow map
 *                   compares the surface against itself and the depth test
 *                   flips triangle by triangle.  The grain then follows the
 *                   terminator, which on the visor is an arc along the top.
 *   interior shell  the scan carries a second, inner copy of the surface.
 *                   Where the two copies are a hair apart they z-fight, and
 *                   the grain appears wherever the copy peeks through.
 *
 * Turning the shadow map off settles the first.  For the second the body
 * is pushed along its own normals, which separates coincident surfaces
 * without moving the silhouette: if the grain follows the offset, it was
 * two surfaces fighting.
 *
 * Usage: node scripts/probe_yxz_face2.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-face2'
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

await park()
await shoot('1-as-is')

// No shadow map at all.
await page.evaluate(() => {
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer)
    renderer.shadowMap.enabled = false
})
await page.waitForTimeout(5000)
await shoot('2-no-shadowmap')

// Shadow map back, but the body stops reading it.  Casting still happens,
// so the ground shadow stays, and only the acne on the body disappears.
await page.evaluate(() => {
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer)
    renderer.shadowMap.enabled = true
  window.__yxzVrm.scene.traverse((object) => {
    if (object.isMesh)
      object.receiveShadow = false
  })
})
await page.waitForTimeout(5000)
await shoot('3-no-receive')

// The body keeps its shadow, but the shadow map is sampled with a much
// larger normal bias and a tighter frustum, so the acne has nowhere to
// hide.
await page.evaluate(() => {
  window.__yxzVrm.scene.traverse((object) => {
    if (object.isMesh)
      object.receiveShadow = true
  })
  const scene = window.__yxzDebug?.scene?.()
  const key = scene?.getObjectByProperty?.('isDirectionalLight', true)
  const light = key ?? scene?.children?.find(c => c.isDirectionalLight)
  if (light) {
    light.shadow.mapSize.set(2048, 2048)
    light.shadow.normalBias = 0.08
    light.shadow.bias = -0.002
    light.shadow.camera.left = -1.8
    light.shadow.camera.right = 1.8
    light.shadow.camera.top = 4.2
    light.shadow.camera.bottom = -0.2
    light.shadow.camera.near = 4.0
    light.shadow.camera.far = 11.0
    light.shadow.camera.updateProjectionMatrix()
    light.shadow.map?.dispose()
    light.shadow.map = null
  }
})
await page.waitForTimeout(6000)
await shoot('4-tight-shadow')

// The last suspect: two coincident surfaces.  Pushing the body along its
// own normals separates them.  If the grain follows the push, it was a
// z-fight between the outer surface and an inner copy.
await page.evaluate(() => {
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    if (!object.userData.__yxzPushed) {
      object.userData.__yxzPushed = true
      const position = object.geometry?.attributes?.position
      const normal = object.geometry?.attributes?.normal
      if (!position || !normal)
        return
      const push = 0.02
      for (let i = 0; i < position.count; i++) {
        position.setXYZ(
          i,
          position.getX(i) + normal.getX(i) * push,
          position.getY(i) + normal.getY(i) * push,
          position.getZ(i) + normal.getZ(i) * push,
        )
      }
      position.needsUpdate = true
    }
  })
})
await page.waitForTimeout(5000)
await shoot('5-normal-push')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
