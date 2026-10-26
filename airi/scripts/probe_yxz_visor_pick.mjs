/** 
 * What is actually in front of the visor?
 *
 * The visor carries a bright bar of light across the middle of it that
 * is not in the panel's own paint -- the texture of the panel has no
 * such mark.  So the bar belongs to something else that is drawn over
 * the panel: a piece of geometry of its own, or a different material.
 *
 * A grid of rays is fired at the visor from the page's own camera, and
 * every hit is reported: which mesh it belongs to, which material, and
 * what colour the texture says that point is.  The bar is the stretch
 * of the grid where the texture colour is bright.
 *
 * Usage:
 *   node scripts/probe_yxz_visor_pick.mjs [baseUrl] [--grid 28]
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
const gridIndex = args.indexOf('--grid')
const grid = gridIndex >= 0 ? Number(args[gridIndex + 1]) : 28

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

const result = await page.evaluate(async (steps) => {
  const THREE = window.__yxzDebug?.three
  const vrm = window.__yxzVrm
  const camera = window.__yxzDebug?.camera?.()
  if (!THREE || !vrm?.scene || !camera)
    return null
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const width = canvas?.clientWidth ?? 1100
  const height = canvas?.clientHeight ?? 1000

  // The head's own box, so the shot is framed on the visor.
  let shell = null
  vrm.scene.traverse((object) => {
    if (object.isMesh && !shell && object.name.startsWith('tripo'))
      shell = object
  })
  if (!shell)
    return null
  shell.updateWorldMatrix(true, false)
  const position = shell.geometry.attributes.position
  const box = new THREE.Box3()
  const point = new THREE.Vector3()
  for (let i = 0; i < position.count; i++) {
    point.fromBufferAttribute(position, i)
    point.applyMatrix4(shell.matrixWorld)
    if (point.y < 2.55 || point.y > 3.25)
      continue
    box.expandByPoint(point)
  }
  const size = new THREE.Vector3()
  box.getSize(size)
  const centre = new THREE.Vector3()
  box.getCenter(centre)

  const look = [centre.x, centre.y, box.max.z]
  const from = [centre.x, centre.y, box.max.z + Math.max(size.x, size.z) * 1.6]
  camera.position.set(from[0], from[1], from[2])
  camera.lookAt(look[0], look[1], look[2])
  const distance = Math.hypot(from[0] - look[0], from[1] - look[1], from[2] - look[2])
  camera.fov = 2 * Math.atan(0.75 / 2 / distance) * 180 / Math.PI
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld(true)

  const raycaster = new THREE.Raycaster()
  raycaster.far = distance * 4
  // The atlas, read once, so the colour of the texture at every hit can
  // be reported.  Three.js flips the image, so v = 0 is the bottom row.
  const atlas = new Map()
  const atlasPixels = (material, hit) => {
    const image = material?.map?.image
    if (!image?.width)
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
    const x = Math.min(entry.width - 1, Math.max(0, Math.round(hit.uv.x * entry.width)))
    const y = Math.min(entry.height - 1, Math.max(0, Math.round((1 - hit.uv.y) * entry.height)))
    const index = (y * entry.width + x) * 4
    return [entry.data[index], entry.data[index + 1], entry.data[index + 2]]
  }
  const rows = []
  for (let row = 0; row < steps; row++) {
    const line = []
    for (let col = 0; col < steps; col++) {
      const ndc = new THREE.Vector2(
        (col + 0.5) / steps * 2 - 1,
        -((row + 0.5) / steps * 2 - 1),
      )
      raycaster.setFromCamera(ndc, camera)
      const hits = raycaster.intersectObjects(vrm.scene.children, true)
      if (!hits.length) {
        line.push(null)
        continue
      }
      const hit = hits[0]
      const material = Array.isArray(hit.object.material)
        ? hit.object.material[hit.face?.materialIndex ?? 0]
        : hit.object.material
      line.push({
        object: hit.object.name,
        material: material?.name ?? null,
        uv: hit.uv ? [Number(hit.uv.x.toFixed(4)), Number(hit.uv.y.toFixed(4))] : null,
        colour: hit.uv ? atlasPixels(material, hit) : null,
        distance: Number(hit.distance.toFixed(4)),
      })
    }
    rows.push(line)
  }
  return { rows, width, height, head: { centre: centre.toArray(), size: size.toArray(), front: box.max.z } }
}, grid)

if (!result) {
  console.log('YXZ_PICK no scene')
}
else {
  const names = new Map()
  result.rows.flat().forEach((cell) => {
    if (!cell)
      return
    const key = `${cell.object} / ${cell.material}`
    names.set(key, (names.get(key) ?? 0) + 1)
  })
  console.log('YXZ_PICK_HEAD', JSON.stringify(result.head))
  console.log('YXZ_PICK_MESHES', JSON.stringify([...names.entries()].sort((a, b) => b[1] - a[1])))
  for (let row = 0; row < result.rows.length; row++) {
    const line = result.rows[row]
      .map((cell) => {
        if (!cell)
          return ' . '
        if (!cell.colour)
          return '      --      '
        const [r, g, b] = cell.colour
        const luma = Math.round((0.2126 * r + 0.7152 * g + 0.0722 * b) / 2.55)
        const uv = cell.uv ? `${cell.uv[0].toFixed(3)},${cell.uv[1].toFixed(3)}` : '--'
        return `${String(luma).padStart(3)} ${uv}`.padEnd(18)
      })
      .join('')
    console.log(`ROW ${String(row).padStart(2, '0')} ${line}`)
  }
}
console.log('ERRORS', JSON.stringify(errors))
await browser.close()
