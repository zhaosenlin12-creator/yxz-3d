/**
 * What the bright streak across the visor actually is.
 *
 * The old probe fired nineteen thousand rays at a 700k vertex mesh and
 * never finished.  This one reads the frame buffer first, keeps only the
 * pixels that are actually bright, and fires a ray at each of those and
 * nothing else, so the same question is answered in seconds.
 *
 * For every bright pixel it reports the meshes the ray passed through,
 * the place in the atlas that was hit, and the colour the atlas holds
 * there.  A streak that is painted on is one mesh with a bright texel; a
 * streak that is a sliver in front of the visor is two meshes with two
 * different atlases at the same pixel; a streak that is a crack is one
 * mesh with a dark texel and something bright behind it.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_streak.mjs [baseUrl] [--out <json>]
 */

import { existsSync, readdirSync, writeFileSync } from 'node:fs'
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
const page = await browser.newPage({ viewport: { width: 1100, height: 1000 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const result = await page.evaluate(async () => {
  const THREE = window.__yxzDebug?.three
  const vrm = window.__yxzVrm
  const camera = window.__yxzDebug?.camera?.()
  const renderer = window.__yxzDebug?.renderer?.()
  const composer = window.__yxzDebug?.composer?.()
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

  // The head's box, measured the way the close-up measures it.
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

  // Draw one frame and read the buffer back, so the pixels that are
  // examined are the pixels the renderer produced.
  if (composer)
    composer.render(0)
  else
    renderer.render(vrm.scene, camera)
  const gl = renderer.getContext()
  const bufferWidth = gl.drawingBufferWidth
  const bufferHeight = gl.drawingBufferHeight
  const pixels = new Uint8Array(bufferWidth * bufferHeight * 4)
  gl.readPixels(0, 0, bufferWidth, bufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels)

  const luminanceAt = (x, y) => {
    // The buffer is bottom-up; the caller works in top-down pixels.
    const row = bufferHeight - 1 - y
    const index = (row * bufferWidth + x) * 4
    return 0.2126 * pixels[index] + 0.7152 * pixels[index + 1] + 0.0722 * pixels[index + 2]
  }

  // The bright pixels, sampled on a grid so a long thin streak is not
  // missed between the samples.
  const bright = []
  for (let y = 0; y < bufferHeight; y += 2) {
    for (let x = 0; x < bufferWidth; x += 2) {
      if (luminanceAt(x, y) < 165)
        continue
      // Only the visor band is of interest, so the white shell and the
      // eyes are excluded by their position in the frame.
      const nx = x / bufferWidth
      const ny = y / bufferHeight
      if (nx < 0.18 || nx > 0.82 || ny < 0.30 || ny > 0.58)
        continue
      bright.push({ x, y })
    }
  }

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

  const raycaster = new THREE.Raycaster()
  raycaster.far = distance * 4
  const meshes = []
  vrm.scene.traverse((object) => {
    if (object.isMesh)
      meshes.push(object)
  })
  // The bright pixels are sampled with a stride, so the streak is not
  // missed between two samples but the number of rays stays small.
  const stride = Math.max(1, Math.ceil(bright.length / 260))
  const hits = []
  for (const point of bright.filter((_, index) => index % stride === 0).slice(0, 260)) {
    const ndc = new THREE.Vector2(
      (point.x + 0.5) / bufferWidth * 2 - 1,
      -((point.y + 0.5) / bufferHeight * 2 - 1),
    )
    raycaster.setFromCamera(ndc, camera)
    const found = raycaster.intersectObjects(meshes, false)
    if (!found.length)
      continue
    const layers = []
    for (const hit of found.slice(0, 4)) {
      const material = Array.isArray(hit.object.material)
        ? hit.object.material[hit.face?.materialIndex ?? 0]
        : hit.object.material
      layers.push({
        object: hit.object.name,
        material: material?.name ?? null,
        uv: hit.uv ? [+hit.uv.x.toFixed(4), +hit.uv.y.toFixed(4)] : null,
        colour: atlasPixels(material, hit.uv),
        distance: +hit.distance.toFixed(4),
        face: hit.faceIndex ?? null,
        point: [hit.point.x, hit.point.y, hit.point.z].map(value => +value.toFixed(4)),
      })
    }
    hits.push({ x: point.x, y: point.y, layers })
  }
  return { hits, bufferWidth, bufferHeight, bright: bright.length }
})

if (!result) {
  console.log('YXZ_STREAK no scene')
}
else {
  console.log('YXZ_STREAK_PIXELS', result.bright, 'rays', result.hits.length)
  const places = new Map()
  for (const hit of result.hits) {
    for (const layer of hit.layers) {
      const key = `${layer.object} uv=${layer.uv ? layer.uv.join(',') : 'none'} rgb=${layer.colour ? layer.colour.join(',') : '-'}`
      places.set(key, (places.get(key) ?? 0) + 1)
    }
  }
  console.log('YXZ_STREAK_PLACES')
  for (const [key, count] of [...places.entries()].sort((a, b) => b[1] - a[1]).slice(0, 30))
    console.log(`  ${String(count).padStart(5)}  ${key}`)
  const describe = layer => `${layer.object}[d=${layer.distance}] uv=${layer.uv ? layer.uv.join(',') : 'none'} rgb=${layer.colour ? layer.colour.join(',') : '-'}`
  for (const hit of result.hits.slice(0, 24))
    console.log(`  ${hit.x} ${hit.y} | ${hit.layers.map(describe).join(' || ')}`)
  if (outFile)
    writeFileSync(outFile, JSON.stringify(result, null, 1))
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
