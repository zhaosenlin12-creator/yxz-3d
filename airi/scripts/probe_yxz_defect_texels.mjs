/** Find the texture texels behind the marks on the close-up captures.
 *
 * The close-up captures are taken from a camera that is not the page's
 * own camera, so the existing screen-to-atlas mapper cannot be pointed
 * at them.  This one uses the same camera, the same pose and the same
 * viewport as the close-up probe, and reports the atlas texel under
 * each requested pixel, so a mark can be repaired on the texels that
 * actually show it.
 *
 * Usage:
 *   node scripts/probe_yxz_defect_texels.mjs <baseUrl> <shot> <x,y> ...
 */

import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
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
    .filter(name => name.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const shot = process.argv[3] ?? 'crown'
const pointArgs = process.argv.slice(4)
const points = pointArgs.length === 1 && pointArgs[0].endsWith('.json')
  ? JSON.parse(readFileSync(pointArgs[0], 'utf8')).map(([x, y]) => ({ x, y }))
  : pointArgs.map(text => {
      const [x, y] = text.split(',').map(Number)
      return { x, y }
    })
if (!points.length)
  throw new Error('no points given')

const cameras = {
  head: { eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  crown: { eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  halo: { eye: [0, 3.3, 3.4], look: [0, 3.5, 0] },
  body: { eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
}
const placement = cameras[shot]
if (!placement)
  throw new Error('unknown shot: ' + shot)

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
try {
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
  await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )
  // The character's living layer keeps moving the head whatever the
  // mixer is doing, so the pose has to be paused before anything is
  // picked: a capture and a pick taken a second apart would be looking
  // at two different places on the model.
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.evaluate(() => {
    const canvas = document.querySelector('.yxz-real-model-canvas canvas')
    for (const element of document.querySelectorAll('body *')) {
      if (element === canvas || element.contains(canvas))
        continue
      element.style.setProperty('display', 'none', 'important')
    }
    const debug = window.__yxzDebug
    debug?.freeze(true)
    debug?.snap?.('YXZ_Idle', 0.7)
  })
  // The layout settles after the rest of the page is hidden, and the
  // resize that follows moves the camera, so the camera is placed only
  // once the canvas has stopped changing size.  Placing it earlier
  // points the picker at a different part of the model than the one the
  // close-up capture shows.
  await page.waitForTimeout(2500)
  await page.waitForTimeout(1200)

  // The camera and the picker run in one go.  The page's resize handler
  // rewrites the camera's position and aim, so any delay between placing
  // the camera and picking would point the picker at a different part of
  // the model than the close-up capture shows.
  const pick = async () => page.evaluate(([points, placement]) => {
    const debug = window.__yxzDebug
    const THREE = debug.three
    const scene = window.__yxzVrm.scene
    const camera = debug.camera()
    camera.position.set(placement.eye[0], placement.eye[1], placement.eye[2])
    camera.lookAt(placement.look[0], placement.look[1], placement.look[2])
    camera.updateProjectionMatrix()
    scene.updateMatrixWorld(true)
    camera.updateMatrixWorld(true)
    const bounds = debug.renderer().domElement.getBoundingClientRect()
    const rays = new THREE.Raycaster()
    const cache = new Map()
    const atlasOf = (material) => {
      if (cache.has(material))
        return cache.get(material)
      const image = material.map?.image
      if (!image)
        return null
      const canvas = document.createElement('canvas')
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0)
      const entry = {
        pixels: context.getImageData(0, 0, canvas.width, canvas.height).data,
        width: image.width,
        height: image.height,
      }
      cache.set(material, entry)
      return entry
    }
    const pick = (x, y) => {
      rays.setFromCamera(
        new THREE.Vector2((x - bounds.x) / bounds.width * 2 - 1, 1 - (y - bounds.y) / bounds.height * 2),
        camera,
      )
      const hit = rays.intersectObject(scene, true)[0]
      if (!hit)
        return { x, y, hit: false }
      const material = Array.isArray(hit.object.material)
        ? hit.object.material[hit.face.materialIndex]
        : hit.object.material
      const atlas = atlasOf(material)
      if (!atlas || !hit.uv)
        return { x, y, mesh: hit.object.name, texel: null }
      const column = Math.floor(hit.uv.x * (atlas.width - 1))
      const row = Math.floor(hit.uv.y * (atlas.height - 1))
      const offset = (row * atlas.width + column) * 4
      return {
        x,
        y,
        mesh: hit.object.name,
        material: material.name,
        texel: [column, row],
        colour: Array.from(atlas.pixels.slice(offset, offset + 3)),
        local: hit.object.worldToLocal(hit.point.clone()).toArray(),
      }
    }
    return {
      bounds: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
      hits: points.map(point => pick(point.x, point.y)),
    }
  }, [points, placement])

  const first = await pick()
  const canvas = page.locator('.yxz-real-model-canvas canvas')
  await canvas.screenshot({ path: 'docs/yxz-audit/defect-texels-shot.png' })
  const second = await pick()

  // The character drifts a little between frames, so the picker is run
  // either side of the capture.  If the two agree, the texels belong to
  // the frame the capture shows.
  let drift = 0
  first.hits.forEach((hit, index) => {
    const other = second.hits[index]
    if (!hit.texel || !other.texel)
      return
    if (hit.texel[0] !== other.texel[0] || hit.texel[1] !== other.texel[1])
      drift += 1
  })
  console.log(`DRIFT ${drift}/${first.hits.length}`)

  const result = first

  console.log(JSON.stringify(result.bounds))
  for (const hit of result.hits)
    console.log(`${hit.x},${hit.y} -> ${hit.mesh ?? 'none'} texel=${hit.texel ? hit.texel.join(',') : 'n/a'} colour=${hit.colour ? hit.colour.join(',') : 'n/a'}`)
  writeFileSync('docs/yxz-audit/defect-texels.json', JSON.stringify(result, null, 2))
}
finally {
  await browser.close()
}
