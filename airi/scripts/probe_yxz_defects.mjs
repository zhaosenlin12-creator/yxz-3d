/**
 * Close-ups of the three places the character still reads as broken.
 *
 * The whole-figure captures answer "does it read as solid" and nothing
 * else.  A defect worth naming is a few millimetres across, so it has to
 * be looked at from close enough that its own shape is the subject --
 * and it has to be looked at through the page's own renderer, with its
 * own lights, its own outline and its own material settings, or the
 * answer is about the capture rather than about the character.
 *
 * The camera positions are measured, not typed: the head's own bounding
 * box is read out of the running model and every shot is framed against
 * it, so the same script works whatever the rig's scale is.
 *
 * Usage:
 * node scripts/probe_yxz_defects.mjs [baseUrl] [outDir]
 *   [--paint off]   render with the paint taken off, to tell a hole in
 *                   the shell from a mark on it
 */

import { mkdirSync, readdirSync } from 'node:fs'
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
const positional = args.filter(token => !token.startsWith('--'))
const baseUrl = positional[0] ?? 'http://localhost:5199'
const outDir = positional[1] ?? 'docs/yxz-audit/defects'
const paintIndex = args.indexOf('--paint')
const paint = paintIndex >= 0 ? args[paintIndex + 1] : 'on'

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

await page.evaluate((paintMode) => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  if (paintMode === 'off') {
    const THREE = window.__yxzDebug?.three
    const vrm = window.__yxzVrm
    if (!THREE || !vrm?.scene)
      return
    // The paint off, the shape left.  A mark that is still there with the
    // paint gone is a hole in the shell; a mark that goes with the paint
    // was only ever a mark.
    const plain = new THREE.MeshStandardMaterial({
      color: 0xd8dce0,
      roughness: 0.55,
      metalness: 0,
      side: THREE.DoubleSide,
    })
    vrm.scene.traverse((object) => {
      if (object.isMesh)
        object.material = plain
    })
  }
}, paint)

await page.waitForTimeout(2500)

// The head's own box, measured off the shell above the shoulders.
const head = await page.evaluate(() => {
  const THREE = window.__yxzDebug?.three
  const vrm = window.__yxzVrm
  if (!THREE || !vrm?.scene)
    return null
  let shell = null
  vrm.scene.traverse((object) => {
    if (object.isMesh && !shell && object.name.startsWith('tripo'))
      shell = object
  })
  if (!shell)
    return null
  // The shell's vertices live in the mesh's own space, and a VRM's shell
  // is scaled and lifted by the rig.  Measuring raw attribute positions
  // puts the whole head under the chin, so everything is taken into
  // world space first.
  shell.updateWorldMatrix(true, false)
  const matrix = shell.matrixWorld
  // The neck, taken from the bone the face hangs off.
  let neckY = null
  vrm.scene.traverse((object) => {
    if (object.name !== 'head' || neckY !== null)
      return
    const world = new THREE.Vector3()
    object.getWorldPosition(world)
    neckY = world.y
  })
  if (neckY === null)
    return null
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
  if (box.isEmpty())
    return null
  const size = new THREE.Vector3()
  box.getSize(size)
  const centre = new THREE.Vector3()
  box.getCenter(centre)
  // The face is on the +z side of the head.
  const front = box.max.z
  return {
    neckY,
    min: box.min.toArray(),
    max: box.max.toArray(),
    size: size.toArray(),
    centre: centre.toArray(),
    front,
  }
})

if (!head) {
  console.log('YXZ_DEFECTS no head box')
  await browser.close()
  process.exit(1)
}

const [hx, hy, hz] = head.centre
const [sx, sy, sz] = head.size
const front = head.front

// Each shot is a point on the head and a direction to look from it.
const shots = [
  // The whole head, so every close-up below can be placed against it.
  {
    name: 'head',
    at: [hx, hy, hz],
    from: [hx + sx * 0.55, hy + sy * 0.12, front + Math.max(sx, sz) * 1.7],
    span: Math.max(sx, sy, sz) * 1.25,
  },
  // The join between the visor and the crown, straight on.
  { name: 'brow', at: [hx, hy + sy * 0.30, front], from: [hx, hy + sy * 0.34, front + sz * 1.5], span: 0.62 },
  // The same join, from three-quarters, where the seam shows its depth.
  { name: 'brow-3q', at: [hx, hy + sy * 0.28, front - sz * 0.05], from: [hx + sx * 0.75, hy + sy * 0.42, front + sz * 1.0], span: 0.62 },
  // One eye, close enough that a speck on the iris is the subject.
  { name: 'eye', at: [hx + sx * 0.22, hy + sy * 0.10, front], from: [hx + sx * 0.22, hy + sy * 0.10, front + sz * 1.1], span: 0.42 },
  // The side of the helmet, where the ear cup is.
  { name: 'ear', at: [hx + sx * 0.46, hy + sy * 0.05, hz + sz * 0.12], from: [hx + sx * 1.5, hy + sy * 0.05, hz + sz * 0.55], span: 0.55 },
  // The visor itself, straight on, for the scratches.
  { name: 'visor', at: [hx, hy + sy * 0.05, front], from: [hx, hy + sy * 0.05, front + sz * 1.4], span: 0.75 },
  // The top of the crown, for the bubble fragments.
  { name: 'crown', at: [hx, hy + sy * 0.42, hz], from: [hx + sx * 0.2, hy + sy * 0.95, hz + sz * 0.8], span: 0.7 },
]

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')
for (const shot of shots) {
  await page.evaluate(([eye, look, span]) => {
    const debug = window.__yxzDebug
    const camera = debug?.camera?.()
    if (!camera)
      return
    camera.position.set(eye[0], eye[1], eye[2])
    camera.lookAt(look[0], look[1], look[2])
    // The frame is set by how much of the head it is asked to show, so
    // the shots are comparable with each other and with the next build.
    const distance = Math.hypot(eye[0] - look[0], eye[1] - look[1], eye[2] - look[2])
    camera.fov = 2 * Math.atan(span / 2 / distance) * 180 / Math.PI
    camera.updateProjectionMatrix()
  }, [shot.from, shot.at, shot.span])
  await page.waitForTimeout(1500)
  const file = path.join(outDir, `${shot.name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file}`)
}

console.log(`HEAD ${JSON.stringify({ centre: head.centre, size: head.size, front })}`)
console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
