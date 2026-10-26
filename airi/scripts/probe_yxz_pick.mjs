/**Raycast at named points on the stage and report what is there.
 *
 * The stage is the only place the shipping look can be judged, so when
 * something on the model looks wrong -- a shard lying across the chin,
 * a tooth along the visor -- the question that needs answering is
 * "which piece of geometry is that".  The answer is a raycast: pick the
 * pixel, and the scene says which surface is under it, where it is,
 * and which texel of the atlas is being shown there.
 *
 * The points are given as x,y in the canvas's own pixels, which is the
 * same space as the screenshots the probes write, so a position can be
 * read straight off one.
 *
 * Usage: node scripts/probe_yxz_pick.mjs [baseUrl] [x,y ...]
 */

import { existsSync, readdirSync } from 'node:fs'
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
const points = process.argv.slice(3).map((pair) => {
  const [x, y] = pair.split(',').map(Number)
  return { x, y }
})

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
// The same viewport the other probes use, so the canvas is the same size
// and the model is framed exactly as it is in the screenshots.
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
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const size = await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const box = canvas.getBoundingClientRect()
  return { width: box.width, height: box.height, left: box.left, top: box.top }
})
console.log('CANVAS', JSON.stringify(size))

// The frame the picks are reported in, so a local position can be read
// against the rest of the model.
const frame = await page.evaluate(() => {
  const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
  const found = []
  scene?.traverse((object) => {
    if (!object.isMesh)
      return
    object.geometry.computeBoundingBox()
    const box = object.geometry.boundingBox
    found.push({
      name: object.name,
      localBox: [box.min.toArray(), box.max.toArray()].map(pair =>
        pair.map(value => Number(value.toFixed(4)))),
      position: object.position.toArray().map(value => Number(value.toFixed(4))),
      scale: object.scale.toArray().map(value => Number(value.toFixed(4))),
    })
  })
  return found
})
console.log('FRAME', JSON.stringify(frame))

// A picture of the canvas, in the same pixels the points are given in.
const shot = path.join('docs', 'yxz-pick-canvas.png')
await page.locator('.yxz-real-model-canvas canvas').screenshot({ path: shot })
console.log('SHOT', shot)

for (const point of points) {
  const hits = await page.evaluate(({ point, size }) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const camera = window.__yxzDebug?.camera?.()
    if (!three || !scene || !camera)
      return null
    const ndc = new three.Vector2(
      (point.x / size.width) * 2 - 1,
      -((point.y / size.height) * 2 - 1),
    )
    const raycaster = new three.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    return raycaster.intersectObject(scene, true).slice(0, 4).map((hit) => {
      const local = hit.object.worldToLocal(hit.point.clone())
      return {
        name: hit.object.name || '(unnamed)',
        distance: Number(hit.distance.toFixed(4)),
        world: [hit.point.x, hit.point.y, hit.point.z].map(v => Number(v.toFixed(4))),
        local: [local.x, local.y, local.z].map(v => Number(v.toFixed(4))),
        uv: hit.uv ? [Number(hit.uv.x.toFixed(5)), Number(hit.uv.y.toFixed(5))] : null,
        face: hit.faceIndex ?? null,
        vertex: hit.face ? hit.face.a : null,
      }
    })
  }, { point, size })
  console.log('PICK', point.x, point.y, JSON.stringify(hits))
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
await browser.close()
