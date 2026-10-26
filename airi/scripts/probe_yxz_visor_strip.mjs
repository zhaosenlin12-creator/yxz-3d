/**
 * Take the flat strip off the visor.
 *
 * The bar is a thin sheet of the head standing in front of the visor.
 * It is thin in a way nothing else on the face is: every one of its
 * corners sits at the same height, so the strip is level from end to
 * end while the visor it lies over curves away underneath it.
 *
 * So the strip is found by that rule -- level to within a thousandth of
 * a unit, in front of the visor, and no wider than the face -- and the
 * frame is drawn with it removed so the repair can be judged.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_strip.mjs [baseUrl] [--out <dir>]
 */

import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
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
  const match = readdirSync(store).filter(entry => entry.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  const exe = path.join(root, revision, 'chrome-win64', 'chrome.exe')
  return readdirSync(root).includes(revision) ? exe : undefined
}

const args = process.argv.slice(2)
const baseUrl = args.filter(token => !token.startsWith('--'))[0] ?? 'http://127.0.0.1:5199'
const outIndex = args.indexOf('--out')
const outDir = outIndex >= 0 ? args[outIndex + 1] : 'docs/yxz-audit/visor-strip'
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 760 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const shots = await page.evaluate(async () => {
  const THREE = window.__yxzDebug?.three
  const vrm = window.__yxzVrm
  const camera = window.__yxzDebug?.camera?.()
  const renderer = window.__yxzDebug?.renderer?.()
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  if (!THREE || !vrm?.scene || !camera || !canvas || !renderer)
    return null

  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)

  let shell = null
  vrm.scene.traverse((object) => {
    if (object.isMesh && !shell && object.name.startsWith('tripo'))
      shell = object
  })
  shell.updateWorldMatrix(true, false)
  let neckY = null
  vrm.scene.traverse((object) => {
    if (object.name !== 'head' || neckY !== null)
      return
    const world = new THREE.Vector3()
    object.getWorldPosition(world)
    neckY = world.y
  })
  const floor = neckY + 0.02
  const position = shell.geometry.attributes.position
  const box = new THREE.Box3()
  const point = new THREE.Vector3()
  for (let i = 0; i < position.count; i++) {
    point.fromBufferAttribute(position, i)
    point.applyMatrix4(shell.matrixWorld)
    if (point.y < floor || Math.abs(point.x) > 0.72 || point.z > 1.05)
      continue
    box.expandByPoint(point)
  }
  const size = new THREE.Vector3()
  box.getSize(size)
  const centre = new THREE.Vector3()
  box.getCenter(centre)
  const front = box.max.z
  const hx = centre.x
  const hy = centre.y
  const sz = size.z

  const look = [hx, hy + size.y * 0.05, front]
  const from = [hx, hy + size.y * 0.05, front + sz * 1.4]
  camera.position.set(from[0], from[1], from[2])
  camera.lookAt(look[0], look[1], look[2])
  const distance = Math.hypot(from[0] - look[0], from[1] - look[1], from[2] - look[2])
  camera.fov = 2 * Math.atan(0.75 / 2 / distance) * 180 / Math.PI
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld(true)

  const draw = () => {
    renderer.render(vrm.scene, camera)
    return canvas.toDataURL('image/png')
  }

  const geometry = shell.geometry
  const index = geometry.index
  const corners = index ? index.count : position.count
  const slots = corners / 3
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const c = new THREE.Vector3()
  const scratch = new THREE.Vector3()
  const cornerAt = (slot) => {
    const vertex = index ? index.getX(slot) : slot
    return scratch.fromBufferAttribute(position, vertex).applyMatrix4(shell.matrixWorld)
  }

  // Level triangles: every corner at the same height.
  const level = []
  for (let t = 0; t < slots; t++) {
    a.copy(cornerAt(t * 3))
    b.copy(cornerAt(t * 3 + 1))
    c.copy(cornerAt(t * 3 + 2))
    const mean = (a.y + b.y + c.y) / 3
    const spread = Math.max(
      Math.abs(a.y - mean), Math.abs(b.y - mean), Math.abs(c.y - mean),
    )
    if (spread > 0.0015)
      continue
    level.push({
      face: t,
      y: mean,
      z: (a.z + b.z + c.z) / 3,
      x: (a.x + b.x + c.x) / 3,
    })
  }

  // The ones in front of the face, level, and across the visor.
  const strip = level.filter((item) => {
    if (item.z < front - 0.16)
      return false
    if (Math.abs(item.x) > 0.30)
      return false
    if (item.y < hy - 0.10 || item.y > hy + 0.34)
      return false
    return true
  })
  const summary = {
    level: level.length,
    strip: strip.length,
    yRange: strip.length ? [Math.min(...strip.map(s => s.y)), Math.max(...strip.map(s => s.y))] : [],
    xRange: strip.length ? [Math.min(...strip.map(s => s.x)), Math.max(...strip.map(s => s.x))] : [],
    zRange: strip.length ? [Math.min(...strip.map(s => s.z)), Math.max(...strip.map(s => s.z))] : [],
  }

  const results = { summary, before: draw() }

  if (strip.length) {
    const doomed = new Set(strip.map(item => item.face))
    const originalIndex = index ? index.array : null
    const built = new Uint32Array(corners)
    let write = 0
    for (let t = 0; t < slots; t++) {
      if (doomed.has(t))
        continue
      for (let k = 0; k < 3; k++)
        built[write++] = originalIndex ? originalIndex[t * 3 + k] : t * 3 + k
    }
    geometry.setIndex(new THREE.BufferAttribute(built.subarray(0, write), 1))
    results.removed = draw()
    geometry.setIndex(new THREE.BufferAttribute(originalIndex ? originalIndex : built.subarray(0, write), 1))
    results.restored = draw()
  }
  return results
})

if (!shots) {
  console.log('YXZ_STRIP no scene')
}
else {
  console.log('YXZ_STRIP_SUMMARY', JSON.stringify(shots.summary))
  for (const name of ['before', 'removed', 'restored']) {
    if (!shots[name])
      continue
    const base64 = shots[name].replace(/^data:image\/png;base64,/, '')
    const file = path.join(outDir, `${name}.png`)
    writeFileSync(file, Buffer.from(base64, 'base64'))
    console.log('YXZ_STRIP_SHOT', file)
  }
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
