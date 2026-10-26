/**
 * The atlas place of the bar on the visor.
 *
 * The bar is drawn on the visor, so the atlas is where it can be
 * repaired.  To repair it, the exact texels have to be known, and the
 * way to know them is to put a ray through the bar itself.
 *
 * So the frame is drawn without any light on it, which leaves the bar
 * as the brightest thing in the middle of a dark panel, and the bar's
 * pixels are found in that picture rather than guessed at.  Only those
 * pixels are then traced back into the atlas.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_bar_uv.mjs [baseUrl] [--out <json>]
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

  // The atlas, read back through a canvas so the pixels are the ones the
  // renderer is using.
  const atlases = new Map()
  const atlasPixels = (material, uv) => {
    const image = material?.map?.image
    if (!image?.width || !uv)
      return null
    if (!atlases.has(image)) {
      const surface = document.createElement('canvas')
      surface.width = image.width
      surface.height = image.height
      const context = surface.getContext('2d', { willReadFrequently: true })
      context.drawImage(image, 0, 0)
      atlases.set(image, {
        width: image.width,
        height: image.height,
        data: context.getImageData(0, 0, image.width, image.height).data,
      })
    }
    const entry = atlases.get(image)
    const x = Math.min(entry.width - 1, Math.max(0, Math.round(uv.x * entry.width)))
    const y = Math.min(entry.height - 1, Math.max(0, Math.round((1 - uv.y) * entry.height)))
    const index = (y * entry.width + x) * 4
    return [entry.data[index], entry.data[index + 1], entry.data[index + 2]]
  }

  // Draw the model with no light on it, so the bar stands out against
  // the visor it is painted on.
  const saved = []
  vrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const source = object.material
    const list = Array.isArray(source) ? source : [source]
    const map = list.find(item => item?.map)?.map
    saved.push([object, source])
    object.material = new THREE.MeshBasicMaterial({ map: map ?? null, color: 0xffffff })
  })
  renderer.render(vrm.scene, camera)
  const gl = renderer.getContext()
  const width = gl.drawingBufferWidth
  const height = gl.drawingBufferHeight
  const pixels = new Uint8Array(width * height * 4)
  gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
  for (const [object, material] of saved)
    object.material = material

  const at = (x, y) => {
    const row = height - 1 - y
    const index = (row * width + x) * 4
    return [pixels[index], pixels[index + 1], pixels[index + 2]]
  }

  // The bar is a long horizontal run of bright pixels on a dark panel.
  // Find the rows that hold one, and the run inside each of them.
  const runs = []
  for (let y = 0; y < height; y++) {
    let start = null
    for (let x = 0; x < width; x++) {
      const [r, g, b] = at(x, y)
      const bright = r > 190 && g > 200 && b > 210
      if (bright && start === null)
        start = x
      if ((!bright || x === width - 1) && start !== null) {
        const end = bright ? x : x - 1
        if (end - start > 60)
          runs.push({ y, x0: start, x1: end })
        start = null
      }
    }
  }
  const bar = runs
    .filter(run => run.y > height * 0.2 && run.y < height * 0.55)
    .sort((a, b) => (b.x1 - b.x0) - (a.x1 - a.x0))[0]

  if (!bar)
    return { runs, width, height, found: false }

  // The band the bar occupies: the run itself, with a margin, so that
  // the ends of the bar and the edges of the run are both covered.
  const bandTop = Math.max(0, bar.y - 26)
  const bandBottom = Math.min(height - 1, bar.y + 26)
  const bandLeft = Math.max(0, bar.x0 - 6)
  const bandRight = Math.min(width - 1, bar.x1 + 6)

  // Trace the bar back into the atlas.
  const raycaster = new THREE.Raycaster()
  raycaster.far = distance * 4
  const meshes = []
  vrm.scene.traverse((object) => {
    if (object.isMesh)
      meshes.push(object)
  })
  const hits = []
  const local = new THREE.Matrix4().copy(shell.matrixWorld).invert()
  const localPoint = new THREE.Vector3()
  for (let y = bandTop; y <= bandBottom; y += 2) {
    for (let x = bandLeft; x <= bandRight; x += 2) {
      const ndc = new THREE.Vector2((x + 0.5) / width * 2 - 1, -((y + 0.5) / height * 2 - 1))
      raycaster.setFromCamera(ndc, camera)
      const found = raycaster.intersectObjects(meshes, false)
      if (!found.length)
        continue
      const hit = found[0]
      localPoint.copy(hit.point).applyMatrix4(local)
      const material = Array.isArray(hit.object.material)
        ? hit.object.material[hit.face?.materialIndex ?? 0]
        : hit.object.material
      hits.push({
        x,
        y,
        distance: +hit.distance.toFixed(4),
        face: hit.faceIndex ?? null,
        local: [localPoint.x, localPoint.y, localPoint.z].map(value => +value.toFixed(4)),
        uv: hit.uv ? [+hit.uv.x.toFixed(5), +hit.uv.y.toFixed(5)] : null,
        colour: atlasPixels(material, hit.uv),
        point: [hit.point.x, hit.point.y, hit.point.z].map(value => +value.toFixed(4)),
      })
    }
  }
  // And the frame with the bar's own faces taken out, so the repair can
  // be judged from the picture instead of from the numbers.
  const results = { runs, bar, hits, width, height, found: true }
  const doomed = new Set(hits.map(hit => hit.face).filter(face => face !== null))
  results.doomed = doomed.size
  const geometry = shell.geometry
  const index = geometry.index
  const corners = index ? index.count : position.count
  const slots = corners / 3
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
  renderer.render(vrm.scene, camera)
  results.removed = canvas.toDataURL('image/png')
  geometry.setIndex(new THREE.BufferAttribute(originalIndex ? originalIndex : built.subarray(0, write), 1))
  renderer.render(vrm.scene, camera)
  return results
})

if (!report) {
  console.log('YXZ_BAR_UV no scene')
}
else {
  console.log('YXZ_BAR_UV_FOUND', report.found, JSON.stringify(report.bar ?? null))
  if (report.hits) {
    console.log('YXZ_BAR_UV_HITS', report.hits.length)
    console.log('YXZ_BAR_UV_FACES', JSON.stringify([...new Set(report.hits.map(hit => hit.face))]))
    for (const hit of report.hits.slice(0, 30))
      console.log(`  ${hit.x} ${hit.y} d=${hit.distance} face=${hit.face} uv=${hit.uv} rgb=${hit.colour}`)
  }
  if (report.removed) {
    const base64 = report.removed.replace(/^data:image\/png;base64,/, '')
    const file = 'docs/yxz-audit/visor-bar-removed.png'
    writeFileSync(file, Buffer.from(base64, 'base64'))
    console.log('YXZ_BAR_UV_REMOVED', file)
  }
  if (outFile)
    writeFileSync(outFile, JSON.stringify(report, null, 1))
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
