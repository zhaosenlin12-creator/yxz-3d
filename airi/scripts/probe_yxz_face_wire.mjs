/**
 * See the sheet that is lying across the face.
 *
 * The bright streak on the visor is not paint: the ray that lands on it
 * hits a surface that is flat to within a thousandth of a unit and that
 * stands clear of the head.  A wireframe says what shape it is in one
 * picture, and the same pass reports the triangles that make it up so
 * that the sheet can be taken out by number rather than by eye.
 *
 * Usage:
 *   node scripts/probe_yxz_face_wire.mjs [baseUrl] [--out <png>] [--json <json>]
 */

import { readdirSync, writeFileSync } from 'node:fs'
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
const outFile = outIndex >= 0 ? args[outIndex + 1] : undefined
const jsonIndex = args.indexOf('--json')
const jsonFile = jsonIndex >= 0 ? args[jsonIndex + 1] : undefined

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1100, height: 1000 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(async () => {
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

  // The flat sheet: every triangle whose three corners sit at the same
  // depth, within a hair, and that depth is in front of the head.
  const geometry = shell.geometry
  const index = geometry.index
  const corners = index ? index.count : position.count
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const c = new THREE.Vector3()
  const scratch = new THREE.Vector3()
  const cornerAt = (slot) => {
    const vertex = index ? index.getX(slot) : slot
    return scratch.fromBufferAttribute(position, vertex).applyMatrix4(shell.matrixWorld)
  }
  const triangles = []
  for (let t = 0; t < corners / 3; t++) {
    a.copy(cornerAt(t * 3))
    b.copy(cornerAt(t * 3 + 1))
    c.copy(cornerAt(t * 3 + 2))
    const spread = Math.max(
      Math.abs(a.z - b.z), Math.abs(b.z - c.z), Math.abs(a.z - c.z),
    )
    if (spread > 0.0015)
      continue
    const maxZ = Math.max(a.z, b.z, c.z)
    if (maxZ < front + 0.02)
      continue
    triangles.push({
      face: t,
      z: +((a.z + b.z + c.z) / 3).toFixed(4),
      y: +((a.y + b.y + c.y) / 3).toFixed(4),
      x: +((a.x + b.x + c.x) / 3).toFixed(4),
      spread: +spread.toFixed(5),
    })
  }
  const planes = new Map()
  for (const triangle of triangles) {
    const key = triangle.z.toFixed(3)
    planes.set(key, (planes.get(key) ?? 0) + 1)
  }

  // The wireframe picture, so the sheet can be seen rather than described.
  const wireframe = new THREE.MeshBasicMaterial({
    color: 0x102030,
    wireframe: true,
    transparent: true,
    opacity: 0.55,
  })
  const originals = []
  vrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    originals.push([object, object.material])
    object.material = wireframe
  })
  renderer.render(vrm.scene, camera)
  const shot = canvas.toDataURL('image/png')
  for (const [object, material] of originals)
    object.material = material
  renderer.render(vrm.scene, camera)

  return {
    shot,
    headBox: { min: box.min.toArray(), max: box.max.toArray(), size: size.toArray() },
    front,
    planes: [...planes.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12),
    triangles: triangles.slice(0, 600),
    triangleCount: triangles.length,
  }
})

if (!report) {
  console.log('YXZ_WIRE no scene')
}
else {
  console.log('YXZ_WIRE_HEAD', JSON.stringify(report.headBox))
  console.log('YXZ_WIRE_FLAT_TRIANGLES', report.triangleCount)
  console.log('YXZ_WIRE_PLANES', JSON.stringify(report.planes))
  if (outFile) {
    const base64 = report.shot.replace(/^data:image\/png;base64,/, '')
    writeFileSync(outFile, Buffer.from(base64, 'base64'))
    console.log('YXZ_WIRE_SHOT', outFile)
  }
  if (jsonFile) {
    writeFileSync(jsonFile, JSON.stringify({
      headBox: report.headBox,
      front: report.front,
      planes: report.planes,
      triangles: report.triangles,
    }, null, 1))
  }
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
