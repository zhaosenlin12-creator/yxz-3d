/**
 * What the live YXZ scene actually contains.
 *
 * Every mesh decision that has to be made -- where the visor ends, which
 * shell is the debris, how big the head is in world units -- needs three
 * numbers that only the running page has: the model's scale, the head's
 * place, and the names and materials of the objects.  Measuring them
 * here rather than guessing them from the source file means the camera
 * positions used for the close-ups and the material sweeps are measured
 * in the same space the renderer uses.
 *
 * Usage: node scripts/probe_yxz_scene.mjs [baseUrl]
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

const baseUrl = process.argv[2] ?? 'http://localhost:5199'

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 800 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const vrm = window.__yxzVrm
  const THREE = debug?.three
  if (!vrm?.scene || !THREE)
    return { error: 'no scene' }

  const box = new THREE.Box3().setFromObject(vrm.scene)
  const size = new THREE.Vector3()
  box.getSize(size)
  const centre = new THREE.Vector3()
  box.getCenter(centre)

  const objects = []
  vrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const materials = (Array.isArray(object.material) ? object.material : [object.material])
      .filter(Boolean)
      .map((material) => ({
        name: material.name,
        mtoon: material.isMToonMaterial === true,
        side: material.side,
        transparent: material.transparent,
        opacity: material.opacity,
        uniforms: material.userData?.shader?.uniforms
          ? Object.keys(material.userData.shader.uniforms).sort()
          : [],
      }))
    const meshBox = new THREE.Box3().setFromObject(object)
    const meshSize = new THREE.Vector3()
    meshBox.getSize(meshSize)
    objects.push({
      name: object.name,
      type: object.type,
      visible: object.visible,
      triangles: object.geometry?.index
        ? object.geometry.index.count / 3
        : (object.geometry?.attributes?.position?.count ?? 0) / 3,
      size: meshSize.toArray().map(v => +v.toFixed(4)),
      centre: meshBox.getCenter(new THREE.Vector3()).toArray().map(v => +v.toFixed(4)),
      materials,
    })
  })

  // The head's own place, measured from the bone the face hangs off.
  let head = null
  vrm.scene.traverse((object) => {
    if (object.name !== 'head' || head)
      return
    const world = new THREE.Vector3()
    object.getWorldPosition(world)
    head = { name: object.name, world: world.toArray().map(v => +v.toFixed(4)) }
  })

  const camera = debug.camera?.()
  return {
    box: {
      min: box.min.toArray().map(v => +v.toFixed(4)),
      max: box.max.toArray().map(v => +v.toFixed(4)),
      size: size.toArray().map(v => +v.toFixed(4)),
      centre: centre.toArray().map(v => +v.toFixed(4)),
    },
    head,
    camera: camera
      ? {
          position: camera.position.toArray().map(v => +v.toFixed(3)),
          fov: camera.fov,
          near: camera.near,
          far: camera.far,
        }
      : null,
    objects,
  }
})

console.log(JSON.stringify(report, null, 2))
console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
