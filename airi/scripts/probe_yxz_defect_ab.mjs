/**
 * Which part of the render stack is drawing the marks on the face?
 *
 * The scan itself is clean -- rendered in Blender from the deployed VRM
 * it has one smooth visor edge and one clean red smile.  So every mark
 * the page shows is drawn by the page, and the page has four things that
 * could be drawing it:
 *
 *   outline   the silhouette pass finds the visor's own edge and inks
 *             it, and closes the cracks between pieces of the scan
 *   rim       MToon's rim term saturates on anything turned away from
 *             the camera, which is most of the visor
 *   mouth     the added `YXZ_Mouth` / `YXZ_MouthCavity` meshes sit on
 *             top of the scan's own red lips
 *   shadow    the visor is a thin shell inside a helmet that shadows it
 *
 * Every variant below is applied to the same running model, from the
 * same camera, with the life layer paused, so a difference between two
 * of them can only be the one thing that was changed.
 *
 * Usage:
 *   node scripts/probe_yxz_defect_ab.mjs [baseUrl] [outDir]
 */

import { mkdirSync } from 'node:fs'
import { existsSync, readdirSync } from 'node:fs'
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
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/defect-ab')
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1100, height: 900 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
// The pause button is what stops the living layer.  `freeze(true)` only
// stops the clip, so without this the head keeps moving from one variant
// to the next and the pictures are not of the same pose.
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

const canvas = page.locator('.yxz-real-model-canvas canvas')

/*
 * One toggle for the whole render stack, installed once, so the
 * variants can be taken from a single load of the page.  Each toggle
 * saves what it is about to change and puts it back, so the variants
 * are independent of each other and the order they run in cannot
 * matter.
 */
await page.evaluate(() => {
  const saved = { rim: [], shadow: [] }
  const state = { outline: true, mouth: true, rim: true, shadow: true, bloom: true }
  window.__yxzState = state
  const eachMaterial = (fn) => {
    window.__yxzDebug?.scene?.().traverse((object) => {
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material])
        fn(m)
    })
  }
  window.__yxzToggle = (key) => {
    if (key === 'baseline') {
      // Put every toggle back, so one view cannot leave the model
      // changed for the next one.
      window.__yxzToggle('no-outline')
      window.__yxzToggle('no-mouth')
      window.__yxzToggle('no-rim')
      window.__yxzToggle('no-shadow')
      window.__yxzToggle('no-bloom')
      state.outline = true
      state.mouth = true
      state.rim = true
      state.shadow = true
      state.bloom = true
      const outline = window.__yxzDebug?.outlinePass?.()
      if (outline)
        outline.enabled = true
      const bloom = window.__yxzDebug?.bloomPass?.()
      if (bloom)
        bloom.enabled = true
      window.__yxzDebug?.scene?.().traverse((object) => {
        if (object.isMesh && (object.name === 'YXZ_Mouth' || object.name === 'YXZ_MouthCavity'))
          object.visible = true
        if (object.isDirectionalLight && saved.shadow.some(entry => entry.object === object))
          object.castShadow = saved.shadow.find(entry => entry.object === object).castShadow
      })
      for (const entry of saved.rim) {
        if (entry.colour)
          entry.m.uniforms.parametricRimColorFactor.value.copy(entry.colour)
        if (typeof entry.mix === 'number')
          entry.m.uniforms.rimLightingMixFactor.value = entry.mix
      }
      return 'baseline'
    }
    if (key === 'no-outline') {
      const pass = window.__yxzDebug?.outlinePass?.()
      if (!pass)
        return 'no-outline: missing'
      state.outline = !state.outline
      pass.enabled = state.outline
      return `outline ${pass.enabled ? 'on' : 'off'}`
    }
    if (key === 'no-mouth') {
      state.mouth = !state.mouth
      window.__yxzDebug?.scene?.().traverse((object) => {
        if (object.isMesh && (object.name === 'YXZ_Mouth' || object.name === 'YXZ_MouthCavity'))
          object.visible = state.mouth
      })
      return 'mouth toggled'
    }
    if (key === 'no-rim') {
      if (!saved.rim.length) {
        eachMaterial((m) => {
          if (!m?.isMToonMaterial)
            return
          saved.rim.push({
            m,
            colour: m.uniforms?.parametricRimColorFactor?.value?.clone(),
            mix: m.uniforms?.rimLightingMixFactor?.value,
          })
        })
      }
      state.rim = !state.rim
      for (const entry of saved.rim) {
        if (state.rim) {
          if (entry.colour)
            entry.m.uniforms.parametricRimColorFactor.value.copy(entry.colour)
          if (typeof entry.mix === 'number')
            entry.m.uniforms.rimLightingMixFactor.value = entry.mix
          continue
        }
        if (entry.colour)
          entry.m.uniforms.parametricRimColorFactor.value.setRGB(0, 0, 0)
        if (typeof entry.mix === 'number')
          entry.m.uniforms.rimLightingMixFactor.value = 0
      }
      return 'rim off'
    }
    if (key === 'no-shadow') {
      if (!saved.shadow.length) {
        window.__yxzDebug?.scene?.().traverse((object) => {
          if (object.isDirectionalLight)
            saved.shadow.push({ object, castShadow: object.castShadow })
        })
      }
      state.shadow = !state.shadow
      for (const entry of saved.shadow)
        entry.object.castShadow = state.shadow ? entry.castShadow : false
      return 'shadow toggled'
    }
    if (key === 'no-bloom') {
      const pass = window.__yxzDebug?.bloomPass?.()
      if (!pass)
        return 'no-bloom: missing'
      state.bloom = !state.bloom
      pass.enabled = state.bloom
      return `bloom ${pass.enabled ? 'on' : 'off'}`
    }
    return 'unknown'
  }
})

/*
 * The frame is put on the face itself.  The mouth mesh's own world
 * position is used to aim it, so the shot does not depend on a guessed
 * height and stays on the same spot whatever the rig is scaled to.
 */
const target = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const scene = debug?.scene?.()
  const out = { mouth: null, eye: null, names: [] }
  /*
   * The mouth mesh's *origin* is the model's origin -- the geometry was
   * built in model space and never moved -- so the origin says nothing
   * about where the mouth is.  The vertices do, but they are in the
   * *bind* pose: the object is skinned to the head bone, and the bone
   * carries it round.  So the skinned position of each vertex is what
   * says where the mouth is, and the centre of those is what the camera
   * is aimed at.
   */
  const centreOf = (object) => {
    const position = object.geometry?.attributes?.position
    if (!position)
      return null
    const scratch = object.position.clone()
    const skinned = typeof object.getVertexPosition === 'function'
    let x = 0
    let y = 0
    let z = 0
    for (let i = 0; i < position.count; i++) {
      if (skinned) {
        object.getVertexPosition(i, scratch)
        x += scratch.x
        y += scratch.y
        z += scratch.z
      }
      else {
        x += position.getX(i)
        y += position.getY(i)
        z += position.getZ(i)
      }
    }
    const count = Math.max(1, position.count)
    const local = { x: x / count, y: y / count, z: z / count }
    const e = object.matrixWorld.elements
    return [
      e[0] * local.x + e[4] * local.y + e[8] * local.z + e[12],
      e[1] * local.x + e[5] * local.y + e[9] * local.z + e[13],
      e[2] * local.x + e[6] * local.y + e[10] * local.z + e[14],
    ]
  }
  scene?.traverse((object) => {
    if (object.isMesh)
      out.names.push(object.name)
    if (object.name === 'YXZ_Mouth' || object.name === 'YXZ_MouthCavity') {
      out.mouth = centreOf(object) ?? out.mouth
    }
    if (object.name === 'YXZ_EyeGlow' && !out.eye) {
      out.eye = centreOf(object)
    }
  })
  return out
})
console.log('MESH NAMES ' + JSON.stringify(target.names))

const VIEWS = [
  // The head is about 1.4 units across on the page, so the camera has to
  // stand further off than that or it is inside the helmet.
  { name: 'mouth', point: target.mouth, dist: 1.05 },
  {
    name: 'visor',
    point: target.eye ? [target.eye[0], target.eye[1] - 0.10, target.eye[2]] : null,
    dist: 1.25,
  },
]
console.log('ANCHORS ' + JSON.stringify(target.mouth) + ' ' + JSON.stringify(target.eye))

async function aim(view) {
  /*
   * The camera is put back after the page's own resize handler has run.
   * That handler puts the camera back where it started, and it runs
   * whenever the canvas changes size -- which hiding the rest of the
   * page does.  So the position is set, and then set again after each
   * wait, and the picture is taken from the last one.
   */
  for (let i = 0; i < 4; i++) {
    await page.evaluate(([point, dist]) => {
      const debug = window.__yxzDebug
      const camera = debug?.camera?.()
      if (!camera || !point)
        return
      camera.position.set(point[0], point[1], point[2] + dist)
      camera.lookAt(point[0], point[1], point[2])
      camera.updateProjectionMatrix()
    }, [view.point, view.dist])
    await page.waitForTimeout(400)
  }
}

const ORDER = ['baseline', 'no-outline', 'no-mouth', 'no-rim', 'no-shadow', 'no-bloom']

for (const view of VIEWS) {
  if (!view.point) {
    console.log('SKIP ' + view.name + ' (no anchor)')
    continue
  }
  for (const name of ORDER) {
    await page.evaluate(([key]) => window.__yxzToggle?.(key), [name])
    await aim(view)
    const file = path.join(outDir, `${view.name}-${name}.png`)
    await canvas.screenshot({ path: file })
    console.log('SHOT ' + file)
  }
}

console.log('ERRORS ' + JSON.stringify(errors))
await browser.close()
