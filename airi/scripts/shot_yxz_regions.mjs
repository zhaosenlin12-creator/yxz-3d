/**
 * Look at parts of the figure at the size they are judged at.
 *
 * The stage view is the one that matters, but a defect that is a
 * millimetre at the stage is a crack across the screen in a close-up, and
 * a defect that is invisible in a close-up is still a defect.  So both
 * are captured here, framed on the landmark itself rather than on a
 * number typed into the script: the head bone for the face, the mouth
 * plate for the mouth, the wing for the wing, the hand for the hand.
 *
 * Usage: node scripts/shot_yxz_regions.mjs [baseUrl] [outDir] [--scale 2]
 */

import { mkdirSync, readdirSync, existsSync } from 'node:fs'
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

function installedChromium() {
  const root = path.join(process.env.LOCALAPPDATA ?? '', 'ms-playwright')
  if (!existsSync(root))
    return undefined
  return readdirSync(root)
    .filter(e => /^chromium-\d+$/.test(e))
    .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))
    .map(e => path.join(root, e, 'chrome-win64', 'chrome.exe'))
    .find(existsSync)
}

const args = process.argv.slice(2)
const flag = (name, fallback) => {
  const at = args.indexOf(`--${name}`)
  return at < 0 ? fallback : args[at + 1]
}
const positional = args.filter((token, index) =>
  !token.startsWith('--') && !(index > 0 && args[index - 1].startsWith('--')))
const baseUrl = positional[0] ?? 'http://127.0.0.1:5199'
const outDir = positional[1] ?? 'docs/yxz-audit/regions'
const scale = Number(flag('scale', 2))

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch({
  executablePath: installedChromium(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({
  viewport: { width: 900, height: 900 },
  deviceScaleFactor: scale,
})
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
// Freeze the figure, so every frame is judged on the same pose.
await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.waitForTimeout(1500)

// Where everything is, in world space.
const scene = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const three = debug.three
  const out = { bones: {}, meshes: [] }
  debug.scene().updateMatrixWorld(true)
  debug.scene().traverse((object) => {
    if (object.isBone && object.name) {
      const p = new three.Vector3()
      object.getWorldPosition(p)
      out.bones[object.name] = p.toArray().map(v => +v.toFixed(4))
    }
    if (object.isMesh && object.name) {
      const geo = object.geometry
      if (!geo.boundingBox)
        geo.computeBoundingBox()
      const box = geo.boundingBox.clone().applyMatrix4(object.matrixWorld)
      out.meshes.push({
        name: object.name,
        min: box.min.toArray().map(v => +v.toFixed(4)),
        max: box.max.toArray().map(v => +v.toFixed(4)),
        tris: geo.index ? geo.index.count / 3 : geo.attributes.position.count / 3,
      })
    }
  })
  return out
})

console.log('BONES')
for (const [name, p] of Object.entries(scene.bones))
  console.log(`  ${name.padEnd(16)} ${p.join(' ')}`)
console.log('MESHES')
for (const m of scene.meshes)
  console.log(`  ${m.name.padEnd(28)} min ${m.min.join(' ')}  max ${m.max.join(' ')}  tris ${m.tris}`)

// The framings.
//
// A region is named by a point on the screen and how far back to stand from
// it.  The point is turned into a world position by casting a ray into the
// scene, so "the lower rim of the visor" means the pixel it is in the
// reference shot, not a coordinate typed in here that goes stale the moment
// the rig moves.  The reference shot is the one taken first, with the
// camera where the page puts it.
const FRAMINGS = [
  { name: 'full', landmark: 'root', distance: 0 },
  { name: 'mouth', atWorld: [0, 2.268, 0.86], distance: 0.42 },
  { name: 'mouth-tagged', atWorld: [0, 2.268, 0.86], distance: 0.42, tint: { YXZ_Mouth: [0, 1, 0], YXZ_MouthCavity: [0, 0, 1] } },
  { name: 'mouth-oblique', atWorld: [0, 2.268, 0.86], distance: 0.42, offset: [-0.22, 0.1, 0] },
  { name: 'visor-rim-left', at: [0.243, 0.472], distance: 0.7 },
]

for (const framing of FRAMINGS) {
  const placed = await page.evaluate(({ landmark, at, atWorld, distance, height, offset, tint }) => {
    const debug = window.__yxzDebug
    const three = debug.three
    const camera = debug.camera()
    const target = new three.Vector3()
    let found = false
    let hit = null
    // The tint is for telling surfaces apart: which sheet is the plate
    // and which is the dish behind it is not something the eye can tell
    // when both are pale, so they are lit in different colours and the
    // picture says which is which.
    if (tint) {
      debug.scene().traverse((object) => {
        if (!object.isMesh || !object.name || !(object.name in tint))
          return
        const colour = tint[object.name]
        object.material = new three.MeshBasicMaterial({
          color: new three.Color(colour[0], colour[1], colour[2]),
          side: three.DoubleSide,
        })
        object.renderOrder = 10
      })
    }
    // The reference camera, so every region is found on the same picture
    // the eye picked it from and not on whatever the last shot left behind.
    const reference = { position: [0, 2.25, 6.4], target: [0, 2.05, 0] }
    camera.position.set(...reference.position)
    camera.lookAt(new three.Vector3(...reference.target))
    // The stage's camera keeps a half-unit near plane, which is right for
    // the stage and clips anything a close-up wants to look at.
    camera.near = 0.02
    camera.far = 100
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld(true)
    if (landmark === 'root') {
      target.set(0, 2.0, 0)
      found = true
    }
    else if (at) {
      // Cast a ray through the point on the screen and take where it lands
      // on the character as the thing to look at.
      const raycaster = new three.Raycaster()
      raycaster.setFromCamera(new three.Vector2(at[0] * 2 - 1, -(at[1] * 2 - 1)), camera)
      const hits = raycaster.intersectObjects(debug.scene().children, true)
      hit = hits.find(entry => entry.object.isMesh && entry.object.visible)
      if (hit) {
        target.copy(hit.point)
        found = true
      }
    }
    else if (atWorld) {
      target.set(...atWorld)
      found = true
    }
    else if (landmark === 'mouth') {
      // The mouth plate, if the rig names one; otherwise the head.
      debug.scene().traverse((object) => {
        if (found || !object.isMesh || !/mouth|lip/i.test(object.name))
          return
        const p = new three.Vector3()
        object.getWorldPosition(p)
        target.copy(p)
        found = true
      })
      if (!found) {
        debug.scene().traverse((object) => {
          if (!object.isBone || object.name !== 'head')
            return
          const p = new three.Vector3()
          object.getWorldPosition(p)
          target.copy(p)
          target.y -= 0.22
        })
      }
    }
    else {
      debug.scene().traverse((object) => {
        if (found || !object.isBone)
          return
        const wanted = landmark === 'leftWing' ? /wing.*l/i : landmark === 'rightHand' ? /hand.*r/i : new RegExp(`^${landmark}$`, 'i')
        if (!wanted.test(object.name))
          return
        const p = new three.Vector3()
        object.getWorldPosition(p)
        target.copy(p)
        found = true
      })
    }
    if (!found)
      return null
    target.y += height ?? 0
    if (distance > 0) {
      camera.position.set(target.x, target.y + 0.04, target.z + distance)
      if (offset) {
        camera.position.x += offset[0]
        camera.position.y += offset[1]
        camera.position.z += offset[2]
      }
      camera.lookAt(target)
      camera.updateProjectionMatrix()
    }
    return {
      target: target.toArray().map(v => +v.toFixed(3)),
      hit: hit ? hit.object.name : null,
    }
  }, framing)

  if (!placed) {
    console.log(`SKIP ${framing.name}: landmark ${framing.landmark} not found`)
    continue
  }
  // The page can reload under the capture -- a dev server rebuild will
  // remount the model and put the camera back where it started -- so the
  // mount is waited for and the camera is set again before every shot.
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )
  await page.waitForTimeout(1200)
  const file = path.join(outDir, `${framing.name}.png`)
  await page.screenshot({ path: file, timeout: 120_000 })
  console.log(`SHOT ${file}  target ${placed.target.join(' ')}  on ${placed.hit}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
