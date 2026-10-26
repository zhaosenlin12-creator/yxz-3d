/**
 * Which term in the render stack draws the marks on the visor?
 *
 * The scan's own face is clean: rendered flat, with the model's own
 * texture and no lighting at all, the visor has one smooth edge and the
 * badge has no smear on it.  Everything that looks broken therefore
 * comes from the stage, not from the asset, and the stage has five
 * things that could be drawing it:
 *
 *   shadow    the visor is a thin shell inside a helmet that casts
 *             shadow on it, and the shadow map's bias tears along that
 *             boundary as a row of teeth
 *   rim       MToon's rim term saturates on any surface whose normal
 *             points away from the camera, and the visor is exactly
 *             that surface
 *   terminator the cel ramp is a few degrees wide, so a surface that
 *             turns away crosses it in one pixel
 *   outline   the depth/normal edge pass finds the visor's own
 *             silhouette and inks a line round it
 *   bloom     the halo's light bleeds over the visor's edge
 *
 * Every variant below is applied to the live model, from the same pose
 * and the same camera, so a difference between two of them can only be
 * the one thing that was changed.
 *
 * Usage:
 *   node scripts/probe_yxz_defect_fix.mjs [baseUrl] [outDir]
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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/defect-fix')
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1 })
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
// to the next and the pictures are not of the same pose -- which makes
// every difference between them meaningless.
await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(2500)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/*
 * The scene's own state is read once, so every variant can start from
 * the same place.  Without this the variants would be cumulative and a
 * difference between two of them would carry every change made before
 * it as well.
 */
const baseline = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const renderer = debug?.renderer?.()
  const lights = []
  let toony = null
  debug?.scene?.().traverse((object) => {
    if (object.isDirectionalLight)
      lights.push([object.name, object.castShadow])
    const material = object.material
    if (!material)
      return
    for (const m of Array.isArray(material) ? material : [material]) {
      if (m?.isMToonMaterial && toony === null)
        toony = m.shadingToonyFactor
    }
  })
  const rim = debug?.scene?.() && (() => {
    let value = null
    debug.scene().traverse((object) => {
      const material = object.material
      if (!material || value)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        const uniform = m.uniforms?.parametricRimColorFactor
        if (uniform?.value) {
          value = [uniform.value.r, uniform.value.g, uniform.value.b]
          return
        }
      }
    })
    return value
  })()
  return {
    shadow: renderer?.shadowMap.enabled ?? true,
    lights,
    toony,
    rim,
    outline: debug?.outlinePass?.()?.enabled ?? true,
    bloom: debug?.bloomPass?.()?.strength ?? 0,
  }
})

async function reset() {
  await page.evaluate((state) => {
    const debug = window.__yxzDebug
    const renderer = debug?.renderer?.()
    if (renderer)
      renderer.shadowMap.enabled = state.shadow
    for (const [name, cast] of state.lights) {
      const light = debug?.scene?.()?.getObjectByName?.(name)
      if (light)
        light.castShadow = cast
    }
    if (state.toony !== null) {
      debug?.scene?.().traverse((object) => {
        const material = object.material
        if (!material)
          return
        for (const m of Array.isArray(material) ? material : [material]) {
          if (m?.isMToonMaterial)
            m.shadingToonyFactor = state.toony
        }
      })
    }
    if (state.rim)
      debug?.setUniform?.('parametricRimColorFactor', state.rim)
    const outline = debug?.outlinePass?.()
    if (outline)
      outline.enabled = state.outline
    const bloom = debug?.bloomPass?.()
    if (bloom)
      bloom.strength = state.bloom
  }, baseline)
}

const SHOTS = [
  { name: 'face', eye: [0, 2.50, 1.95], look: [0, 2.42, 0.30] },
  { name: 'crown', eye: [0.35, 3.30, 2.45], look: [0, 2.90, 0.40] },
]

async function aim(eye, look) {
  await page.evaluate(([eyeValue, lookValue]) => {
    const camera = window.__yxzDebug?.camera?.()
    camera.position.set(...eyeValue)
    camera.lookAt(...lookValue)
    camera.updateProjectionMatrix()
  }, [eye, look])
  await page.waitForTimeout(700)
}

async function shoot(prefix) {
  for (const shot of SHOTS) {
    await aim(shot.eye, shot.look)
    await canvas.screenshot({ path: path.join(outDir, `${prefix}-${shot.name}.png`) })
  }
}

/*
 * Each variant is expressed as the change it makes, and the state is
 * reset from the live scene's own defaults before it is applied, so a
 * variant never inherits anything from the one before it.
 */
const NO_SHADOW = `
  const renderer = window.__yxzDebug?.renderer?.()
  if (renderer) renderer.shadowMap.enabled = false
  window.__yxzDebug?.scene?.().traverse((object) => {
    if (object.isDirectionalLight) object.castShadow = false
  })
`
const NO_RIM = `
  window.__yxzDebug?.setUniform?.('parametricRimColorFactor', [0, 0, 0])
`
const WIDE_TERMINATOR = `
  window.__yxzDebug?.scene?.().traverse((object) => {
    const material = object.material
    if (!material) return
    for (const m of Array.isArray(material) ? material : [material]) {
      if (m?.isMToonMaterial) m.shadingToonyFactor = 0.2
    }
  })
`

const variants = [
  ['1-baseline', ''],
  ['2-no-shadow', NO_SHADOW],
  ['3-rim-off', NO_RIM],
  ['4-wide-terminator', WIDE_TERMINATOR],
  ['5-no-outline', `const pass = window.__yxzDebug?.outlinePass?.(); if (pass) pass.enabled = false`],
  ['6-no-bloom', `const pass = window.__yxzDebug?.bloomPass?.(); if (pass) pass.strength = 0`],
  ['7-no-shadow-no-rim', NO_SHADOW + NO_RIM],
  ['8-no-shadow-no-rim-wide', NO_SHADOW + NO_RIM + WIDE_TERMINATOR],
]

for (const [name, code] of variants) {
  await reset()
  if (code)
    await page.evaluate((source) => {
      // eslint-disable-next-line no-new-func
      new Function(source)()
    }, code)
  await page.waitForTimeout(1400)
  await shoot(name)
  console.log('VARIANT', name)
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
