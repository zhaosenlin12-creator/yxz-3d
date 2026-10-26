/**
 * Find the bar on the visor, and try taking it off.
 *
 * The unlit picture shows the bar as a clean rectangle of near-white
 * texels, and the ray that lands on it reports an atlas place inside
 * the helmet's own white.  So the bar is a piece of the head that is
 * standing in front of the visor and is wearing the helmet's colour.
 *
 * This marks the faces that sample that patch of the atlas, paints
 * them, and then deletes them and takes a second picture, so the
 * repair can be judged before anything is rebuilt.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_bar_fix.mjs [baseUrl] [--out <dir>]
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
const outDir = outIndex >= 0 ? args[outIndex + 1] : 'docs/yxz-audit/visor-bar-fix'
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
  const uv = geometry.attributes.uv
  const index = geometry.index
  const corners = index ? index.count : position.count
  const slots = index ? index.count / 3 : position.count / 3

  // The patch of the atlas the bar wears: the white of the helmet.
  //
  // The test is on the corners and not on the middle of a face.  A face
  // of the strip is long and thin and reaches right across the patch,
  // so its own middle is somewhere else entirely, and a test on the
  // middle finds a different set of faces than the one that is drawn.
  const u0 = 0.534
  const u1 = 0.548
  const v0 = 0.806
  const v1 = 0.822
  const marked = []
  for (let t = 0; t < slots; t++) {
    let hit = false
    for (let k = 0; k < 3; k++) {
      const corner = index ? index.getX(t * 3 + k) : t * 3 + k
      const cu = uv.getX(corner)
      const cv = uv.getY(corner)
      if (cu >= u0 && cu <= u1 && cv >= v0 && cv <= v1)
        hit = true
    }
    if (hit)
      marked.push(t)
  }

  const results = { marked: marked.length }
  results.before = draw()

  // Paint them, so the picture says where they are.
  const painted = new THREE.MeshBasicMaterial({ color: 0xff2060 })
  const paintedIndex = new Uint32Array(marked.length * 3)
  let at = 0
  for (const t of marked) {
    for (let k = 0; k < 3; k++)
      paintedIndex[at++] = index ? index.getX(t * 3 + k) : t * 3 + k
  }
  const paintedGeometry = geometry.clone()
  paintedGeometry.setIndex(new THREE.BufferAttribute(paintedIndex, 1))
  const paintedMesh = new THREE.Mesh(paintedGeometry, painted)
  paintedMesh.frustumCulled = false
  shell.parent.add(paintedMesh)
  results.painted = draw()
  shell.parent.remove(paintedMesh)
  paintedGeometry.dispose()

  // Take them off, and take a third picture.
  const kept = []
  const originalIndex = index ? index.array : null
  const built = new Uint32Array(corners)
  let write = 0
  for (let t = 0; t < slots; t++) {
    if (marked.includes(t))
      continue
    for (let k = 0; k < 3; k++)
      built[write++] = originalIndex ? originalIndex[t * 3 + k] : t * 3 + k
  }
  geometry.setIndex(new THREE.BufferAttribute(built.subarray(0, write), 1))
  results.removed = draw()

  // And put them back.
  geometry.setIndex(new THREE.BufferAttribute(originalIndex ? originalIndex : built.subarray(0, write), 1))
  results.restored = draw()
  return results
})

if (!shots) {
  console.log('YXZ_BAR_FIX no scene')
}
else {
  console.log('YXZ_BAR_FIX_MARKED', shots.marked)
  for (const name of ['before', 'painted', 'removed', 'restored']) {
    if (!shots[name])
      continue
    const base64 = shots[name].replace(/^data:image\/png;base64,/, '')
    const file = path.join(outDir, `${name}.png`)
    writeFileSync(file, Buffer.from(base64, 'base64'))
    console.log('YXZ_BAR_FIX_SHOT', file)
  }
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
