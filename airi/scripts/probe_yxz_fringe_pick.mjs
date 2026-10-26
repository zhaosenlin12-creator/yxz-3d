/**
 * What is drawing the bright fringe along the visor's edge?
 *
 * The camera is put exactly where the head probe puts it, and then the
 * pixels of the fringe are raycast, so the answer names the mesh, the
 * texture coordinate and the face that is responsible.
 *
 * Usage:
 *   node scripts/probe_yxz_fringe_pick.mjs [baseUrl]
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
  const match = readdirSync(store).filter(name => name.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(name => name.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64/chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 1000 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(2500)

const anchor = await page.evaluate(() => {
  const scene = window.__yxzDebug?.scene?.()
  let out = null
  scene?.traverse((object) => {
    if (object.name !== 'YXZ_Mouth' || out)
      return
    const position = object.geometry.attributes.position
    const scratch = object.position.clone()
    let x = 0
    let y = 0
    let z = 0
    for (let i = 0; i < position.count; i++) {
      object.getVertexPosition(i, scratch)
      x += scratch.x
      y += scratch.y
      z += scratch.z
    }
    const e = object.matrixWorld.elements
    const lx = x / position.count
    const ly = y / position.count
    const lz = z / position.count
    out = [
      e[0] * lx + e[4] * ly + e[8] * lz + e[12],
      e[1] * lx + e[5] * ly + e[9] * lz + e[13],
      e[2] * lx + e[6] * ly + e[10] * lz + e[14],
    ]
  })
  return out
})

for (let i = 0; i < 4; i++) {
  await page.evaluate(([point]) => {
    const camera = window.__yxzDebug?.camera?.()
    if (!camera)
      return
    camera.position.set(point[0], point[1] + 0.04, point[2] + 1.75)
    camera.lookAt(point[0], point[1] + 0.06, point[2])
    camera.updateProjectionMatrix()
  }, [anchor])
  await page.waitForTimeout(320)
}

await page.locator('.yxz-real-model-canvas canvas').screenshot({ path: 'docs/yxz-audit/fringe-pick.png' })

const size = await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const box = canvas.getBoundingClientRect()
  return { width: box.width, height: box.height }
})

for (const point of [[150, 592], [170, 596], [190, 601], [210, 606], [240, 612], [300, 625]]) {
  const hits = await page.evaluate(({ point, size }) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.()
    const camera = window.__yxzDebug?.camera?.()
    if (!three || !scene || !camera)
      return null
    const ndc = new three.Vector2(
      (point.x / size.width) * 2 - 1,
      -((point.y / size.height) * 2 - 1),
    )
    const raycaster = new three.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    return raycaster.intersectObject(scene, true).slice(0, 3).map((hit) => ({
      name: hit.object.name || '(unnamed)',
      distance: Number(hit.distance.toFixed(4)),
      uv: hit.uv ? [Number(hit.uv.x.toFixed(5)), Number(hit.uv.y.toFixed(5))] : null,
      face: hit.faceIndex ?? null,
    }))
  }, { point, size })
  console.log('PICK', point[0], point[1], JSON.stringify(hits))
}

// Where the mouth plate actually sits on the face.  The plate's inner
// ring is the edge of its hole and its outer ring is its border, and
// both are projected onto the picture, so the two curves can be drawn
// over the face and say what the plate covers.
const outline = await page.evaluate(() => {
  const three = window.__yxzDebug?.three
  const scene = window.__yxzDebug?.scene?.()
  const camera = window.__yxzDebug?.camera?.()
  if (!three || !scene || !camera)
    return null
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const box = canvas.getBoundingClientRect()
  let plate = null
  scene.traverse((object) => {
    if (object.name !== 'YXZ_Mouth' || plate)
      return
    const position = object.geometry.attributes.position
    const scratch = object.position.clone()
    const points = []
    for (let i = 0; i < position.count; i++) {
      object.getVertexPosition(i, scratch)
      const world = scratch.clone().applyMatrix4(object.matrixWorld)
      const ndc = world.clone().project(camera)
      points.push([
        (ndc.x * 0.5 + 0.5) * box.width,
        (-ndc.y * 0.5 + 0.5) * box.height,
      ])
    }
    plate = points
  })
  if (!plate)
    return null
  const rings = 28
  const segments = 144
  const ring = (index) => {
    const out = []
    for (let s = 0; s < segments; s += 2)
      out.push(plate[index * segments + s])
    return out
  }
  return { inner: ring(0), outer: ring(rings - 1) }
})
if (outline) {
  const { writeFileSync } = await import('node:fs')
  writeFileSync('docs/yxz-audit/plate-outline.json', JSON.stringify(outline))
  console.log('OUTLINE rings', outline.inner.length, outline.outer.length)
}

console.log('ERRORS', JSON.stringify(errors))
await browser.close()
