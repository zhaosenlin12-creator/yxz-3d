/**
 * Find the texture of the bar of light on the visor.
 *
 * The visor carries a bright bar across the middle of it that is not
 * part of the panel's paint, and a jagged crack beside it.  Both are
 * in the texture rather than in the shape -- with the paint taken off
 * they are gone -- but they are thin enough that a grid of rays over
 * the whole head steps straight over them.
 *
 * So the rays are aimed where the bar is: the same camera, the same
 * frame, and a fine grid across the stretch of the picture the bar
 * occupies.  Every hit is reported with the colour the texture says
 * that point is, and the bright ones are the bar.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_bar.mjs [baseUrl] [--box x0,y0,x1,y1]
 */

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

const args = process.argv.slice(2)
const baseUrl = args.filter(t => !t.startsWith('--'))[0] ?? 'http://127.0.0.1:5199'
const boxIndex = args.indexOf('--box')
const region = boxIndex >= 0
  ? args[boxIndex + 1].split(',').map(Number)
  : [280, 420, 760, 500]
const stepIndex = args.indexOf('--step')
const step = stepIndex >= 0 ? Number(args[stepIndex + 1]) : 4

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

const result = await page.evaluate(async ([region, step]) => {
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

  let shell = null
  vrm.scene.traverse((object) => {
    if (object.isMesh && !shell && object.name.startsWith('tripo'))
      shell = object
  })
  shell.updateWorldMatrix(true, false)
  const matrix = shell.matrixWorld
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
    point.applyMatrix4(matrix)
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
  const sy = size.y
  const sz = size.z
  const eye = [hx, hy + sy * 0.05, front]
  const look = [hx, hy + sy * 0.05, front]
  const from = [hx, hy + sy * 0.05, front + sz * 1.4]
  camera.position.set(from[0], from[1], from[2])
  camera.lookAt(look[0], look[1], look[2])
  const distance = Math.hypot(from[0] - look[0], from[1] - look[1], from[2] - look[2])
  camera.fov = 2 * Math.atan(0.75 / 2 / distance) * 180 / Math.PI
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld(true)

  const atlas = new Map()
  const atlasPixels = (material, uv, dx = 0, dy = 0) => {
    const image = material?.map?.image
    if (!image?.width || !uv)
      return null
    if (!atlas.has(image)) {
      const surface = document.createElement('canvas')
      surface.width = image.width
      surface.height = image.height
      const context = surface.getContext('2d', { willReadFrequently: true })
      context.drawImage(image, 0, 0)
      atlas.set(image, {
        width: image.width,
        height: image.height,
        data: context.getImageData(0, 0, image.width, image.height).data,
      })
    }
    const entry = atlas.get(image)
    const x = Math.min(entry.width - 1, Math.max(0, Math.round(uv.x * entry.width) + dx))
    const y = Math.min(entry.height - 1, Math.max(0, Math.round((1 - uv.y) * entry.height) + dy))
    const index = (y * entry.width + x) * 4
    return [entry.data[index], entry.data[index + 1], entry.data[index + 2]]
  }

  const raycaster = new THREE.Raycaster()
  raycaster.far = distance * 4
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  const hits = []
  for (let py = region[1]; py <= region[3]; py += step) {
    for (let px = region[0]; px <= region[2]; px += step) {
      const ndc = new THREE.Vector2((px + 0.5) / width * 2 - 1, -((py + 0.5) / height * 2 - 1))
      raycaster.setFromCamera(ndc, camera)
      const found = raycaster.intersectObjects(vrm.scene.children, true)
      if (!found.length)
        continue
      const layers = []
      for (const hit of found.slice(0, 3)) {
        const material = Array.isArray(hit.object.material)
          ? hit.object.material[hit.face?.materialIndex ?? 0]
          : hit.object.material
        layers.push({
          object: hit.object.name,
          material: material?.name ?? null,
          uv: hit.uv ? [hit.uv.x, hit.uv.y] : null,
          colour: atlasPixels(material, hit.uv),
        })
      }
      hits.push({
        px,
        py,
        layers,
      })
    }
  }
  return { hits, width, height }
}, [region, step])

if (!result) {
  console.log('YXZ_BAR no scene')
}
else {
  console.log('YXZ_BAR_CANVAS', JSON.stringify([result.width, result.height]))
  // Every ray that lands on the dark blue of the panel, with what lies
  // behind it: a mark on the panel is a mark in the texture, but a
  // surface fighting with another surface shows two different places in
  // the texture at the same pixel.
  const isNavy = colour => colour && colour[2] > colour[0] + 25 && colour[2] < 215 && colour[0] < 140
  const bright = result.hits.filter(hit => {
    const first = hit.layers[0]
    if (!first?.colour || !isNavy(first.colour))
      return false
    const second = hit.layers[1]
    return second && second.uv && (!first.uv
      || Math.abs(second.uv[0] - first.uv[0]) > 0.002
      || Math.abs(second.uv[1] - first.uv[1]) > 0.002)
  })
  console.log('YXZ_BAR_HITS', result.hits.length, 'bright', bright.length)
  for (const hit of bright.slice(0, 60)) {
    const describe = layer => {
      const uv = layer.uv ? layer.uv.map(v => v.toFixed(4)).join(',') : 'none'
      const rgb = layer.colour ? layer.colour.join(',') : '-'
      return layer.object + ' uv=' + uv + ' rgb=' + rgb
    }
    console.log('  ' + hit.px + ' ' + hit.py + ' | ' + hit.layers.map(describe).join(' || '))
  }
  const places = new Map()
  for (const hit of bright) {
    const first = hit.layers[0]
    const second = hit.layers[1]
    if (!first?.uv || !second?.uv)
      continue
    const key = first.uv.map(v => v.toFixed(3)).join(',') + ' vs ' + second.uv.map(v => v.toFixed(3)).join(',')
    places.set(key, (first.colour ?? []).join(',') + ' / ' + (second.colour ?? []).join(','))
  }
  console.log('YXZ_BAR_PLACES', JSON.stringify([...places.entries()]))
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
