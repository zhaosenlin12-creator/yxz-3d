/**
 * What kind of thing is the bright streak on the visor?
 *
 * A streak can be three different things and they need three different
 * repairs.  If it is paint, it is in the atlas and the atlas is the thing
 * to change.  If it is a sheet of geometry lying across the visor, the
 * mesh is the thing to change.  If it is light, the material is the thing
 * to change, and no amount of editing the file will help.
 *
 * So the same frame is drawn four ways: as it is, with the texture but
 * without any light, with the normals instead of the colour, and as a
 * flat silhouette.  A streak that survives all four is geometry or
 * texture; a streak that only survives the first is light.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_ab.mjs [baseUrl] [--out <dir>]
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
const outDir = outIndex >= 0 ? args[outIndex + 1] : 'docs/yxz-audit/visor-ab'
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

  // The visor shot, exactly as the close-up frames it.
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
  const saved = []
  vrm.scene.traverse((object) => {
    if (object.isMesh)
      saved.push([object, object.material, object.visible])
  })

  const results = {}
  results.lit = draw()

  // The texture without any light on it.
  for (const [object] of saved) {
    const source = object.material
    const list = Array.isArray(source) ? source : [source]
    const map = list.find(item => item?.map)?.map
    object.material = new THREE.MeshBasicMaterial({ map: map ?? null, color: 0xffffff })
  }
  results.unlit = draw()

  // The normals in place of the colour.
  for (const [object] of saved) {
    object.material = new THREE.MeshNormalMaterial()
  }
  results.normals = draw()

  // A flat silhouette: everything the same colour.
  for (const [object] of saved) {
    object.material = new THREE.MeshBasicMaterial({ color: 0x8899aa })
  }
  results.silhouette = draw()

  for (const [object, material, visible] of saved) {
    object.material = material
    object.visible = visible
  }
  draw()
  return results
})

if (!shots) {
  console.log('YXZ_AB no scene')
}
else {
  for (const [name, data] of Object.entries(shots)) {
    const base64 = data.replace(/^data:image\/png;base64,/, '')
    const file = path.join(outDir, `${name}.png`)
    writeFileSync(file, Buffer.from(base64, 'base64'))
    console.log('YXZ_AB_SHOT', file)
  }
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
