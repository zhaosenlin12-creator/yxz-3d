/**
 * Find the bright defects on the character and report where they live in
 * the texture atlas.
 *
 * A pale line across the chin and a mark on the visor read as scratches
 * on the model, but the flat-geometry pass shows nothing there, so they
 * are drawn by the texture.  That means the fix belongs in the atlas,
 * and to edit the atlas the defect has to be found in it -- which means
 * the defect's UV coordinate is needed.
 *
 * So the model is rendered with its base colour and no lighting at all,
 * the pixels that are pure white are clustered, and every cluster is
 * raycast back through the scene.  The raycast reports the UV of the
 * texel that is actually being shown, which is the coordinate the
 * atlas has to be edited at.
 *
 * Usage: node scripts/probe_yxz_uvdefects.mjs [baseUrl] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
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
const outDir = process.argv[3] ?? 'docs/yxz-uvdefects'
await mkdir(outDir, { recursive: true })

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

// Swap to the base colour with no lighting, so what is on screen is
// exactly what the atlas says.
await page.evaluate(() => {
  const three = window.__yxzDebug?.three
  const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
  if (!three || !scene)
    return
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer) {
    renderer.toneMapping = three.NoToneMapping
    renderer.outputColorSpace = three.SRGBColorSpace
  }
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
  scene.traverse((object) => {
    if (!object.isMesh)
      return
    const original = Array.isArray(object.material) ? object.material[0] : object.material
    object.material = new three.MeshBasicMaterial({
      map: original?.map ?? null,
      side: three.FrontSide,
    })
  })
})
await page.waitForTimeout(2500)

const file = path.join(outDir, 'albedo.png')
await canvas.screenshot({ path: file })

const { data, info } = await sharp(file).raw().toBuffer({ resolveWithObject: true })
const { width, height, channels } = info

// Pure white pixels, grouped into blobs.
const hot = new Uint8Array(width * height)
for (let i = 0; i < width * height; i++) {
  const p = i * channels
  const r = data[p]
  const g = data[p + 1]
  const b = data[p + 2]
  if (r >= 250 && g >= 250 && b >= 250 && Math.max(r, g, b) - Math.min(r, g, b) <= 8)
    hot[i] = 1
}

const seen = new Uint8Array(width * height)
const clusters = []
for (let i = 0; i < hot.length; i++) {
  if (!hot[i] || seen[i])
    continue
  const stack = [i]
  seen[i] = 1
  const members = []
  while (stack.length) {
    const at = stack.pop()
    members.push(at)
    const x = at % width
    const y = (at / width) | 0
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = x + dx
      const ny = y + dy
      if (nx < 0 || ny < 0 || nx >= width || ny >= height)
        continue
      const n = ny * width + nx
      if (hot[n] && !seen[n]) {
        seen[n] = 1
        stack.push(n)
      }
    }
  }
  if (members.length < 12)
    continue
  let sumX = 0
  let sumY = 0
  let minX = width
  let maxX = 0
  let minY = height
  let maxY = 0
  for (const at of members) {
    const x = at % width
    const y = (at / width) | 0
    sumX += x
    sumY += y
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
  }
  clusters.push({
    area: members.length,
    cx: Math.round(sumX / members.length),
    cy: Math.round(sumY / members.length),
    box: [minX, minY, maxX - minX + 1, maxY - minY + 1],
  })
}
clusters.sort((a, b) => b.area - a.area)
console.log('WHITE_CLUSTERS', clusters.length)
for (const cluster of clusters.slice(0, 12))
  console.log('CLUSTER', JSON.stringify(cluster))

// Raycast each cluster and report the UV of the texel that is drawn.
for (const [index, cluster] of clusters.slice(0, 12).entries()) {
  const hits = await page.evaluate(({ cluster, width, height }) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const camera = window.__yxzDebug?.camera?.()
    if (!three || !scene || !camera)
      return null
    const ndc = new three.Vector2(
      (cluster.cx / width) * 2 - 1,
      -((cluster.cy / height) * 2 - 1),
    )
    const raycaster = new three.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    return raycaster.intersectObject(scene, true).slice(0, 3).map(hit => ({
      name: hit.object.name || '(unnamed)',
      distance: Number(hit.distance.toFixed(4)),
      uv: hit.uv ? [Number(hit.uv.x.toFixed(5)), Number(hit.uv.y.toFixed(5))] : null,
      // Where the hit lands in the 4096-pixel atlas.
      texel: hit.uv
        ? [Math.round(hit.uv.x * 4096), Math.round((1 - hit.uv.y) * 4096)]
        : null,
    }))
  }, { cluster, width, height })
  console.log('UVDEFECT', index, JSON.stringify(hits))
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
