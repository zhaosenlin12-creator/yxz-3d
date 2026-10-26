/** What the bright bar on the visor actually is.
 *
 * The visor carries a bright bar across it with a jagged crack beside
 * it.  The bar is dimmer than it was before the bump was pushed back,
 * but it is still there, so whatever it is was not the bump.
 *
 * So this aims rays at it from the same camera the close-up uses and
 * reports, for every hit, which mesh it landed on, where in the atlas
 * that is, and what colour the atlas says is there.  A mark on the
 * panel is one mesh with a bright texel; a mark in front of the panel
 * is two meshes with two different atlases at the same pixel.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_bar2.mjs [baseUrl] [--out <json>]
 */

import { writeFileSync } from 'node:fs'
import { readdirSync } from 'node:fs'
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
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  if (!THREE || !vrm?.scene || !camera || !canvas)
    return null
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)

  // The head's box, measured the same way the close-up measures it.
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

  // The atlas, read back through a canvas so the pixels are the ones
  // the renderer is using.
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
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  const hits = []
  // The bar sits in the upper-left third of the visor picture.
  for (let py = 380; py <= 520; py += 2) {
    for (let px = 260; px <= 800; px += 2) {
      const ndc = new THREE.Vector2((px + 0.5) / width * 2 - 1, -((py + 0.5) / height * 2 - 1))
      raycaster.setFromCamera(ndc, camera)
      const found = raycaster.intersectObjects(vrm.scene.children, true)
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
        })
      }
      hits.push({ px, py, layers })
    }
  }
  return { hits, width, height }
})

if (!result) {
  console.log('YXZ_BAR2 no scene')
}
else {
  const bright = result.hits.filter((hit) => {
    const first = hit.layers[0]
    if (!first?.colour)
      return false
    const [r, g, b] = first.colour
    return r > 120 && g > 120 && b > 120
  })
  console.log('YXZ_BAR2_HITS', result.hits.length, 'bright', bright.length)
  const places = new Map()
  for (const hit of bright) {
    for (const layer of hit.layers) {
      const key = `${layer.object} uv=${layer.uv ? layer.uv.join(',') : 'none'}`
      places.set(key, (places.get(key) ?? 0) + 1)
    }
  }
  console.log('YXZ_BAR2_PLACES')
  for (const [key, count] of [...places.entries()].sort((a, b) => b[1] - a[1]).slice(0, 30))
    console.log(`  ${String(count).padStart(5)}  ${key}`)
  for (const hit of bright.slice(0, 20)) {
    const describe = layer => `${layer.object}[d=${layer.distance}] uv=${layer.uv ? layer.uv.join(',') : 'none'} rgb=${layer.colour ? layer.colour.join(',') : '-'}`
    console.log(`  ${hit.px} ${hit.py} | ${hit.layers.map(describe).join(' || ')}`)
  }
  if (outFile)
    writeFileSync(outFile, JSON.stringify(result, null, 1))
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
