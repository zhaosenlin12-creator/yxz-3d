/** Try a few looks on the running model, one at a time.
 *
 * The look of a toon character is not one number: it is the ramp, the
 * shade colour, the rim and the lights together.  So a variant here is a
 * whole set of settings -- uniforms on the materials and values on the
 * lights -- and each one is applied to the live model and shot from the
 * same pose, so two pictures differ by exactly one set.
 *
 * Usage:
 *   node scripts/probe_yxz_look.mjs [baseUrl] [outDir] [variants.json]
 */

import { mkdirSync, readFileSync, readdirSync } from 'node:fs'
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
  const match = (await import('node:fs')).readdirSync(store)
    .filter(e => e.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

async function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(e => e.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-diag/look'
const variantsFile = process.argv[4] ?? 'docs/yxz-diag/look-variants.json'
const variants = JSON.parse(readFileSync(variantsFile, 'utf8'))

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: await resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({
  viewport: { width: 1040, height: 900 },
  deviceScaleFactor: 1,
})
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
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
await page.waitForTimeout(2000)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')
for (const [index, variant] of variants.entries()) {
  const applied = await page.evaluate((settings) => {
    const debug = window.__yxzDebug
    const report = []
    for (const [name, value] of Object.entries(settings.uniforms ?? {})) {
      report.push(`${name}=${debug?.setUniform?.(name, value)}`)
    }
    const scene = debug?.scene?.()
    const lights = []
    scene?.traverse((object) => {
      if (object.isLight)
        lights.push(object)
    })
    for (const [key, value] of Object.entries(settings.lights ?? {})) {
      const index = lights.findIndex(light => light.userData?.yxzName === key
        || light.name === key)
      if (index < 0) {
        report.push(`light:${key}=missing`)
        continue
      }
      const light = lights[index]
      if (value.intensity !== undefined)
        light.intensity = value.intensity
      if (value.color !== undefined)
        light.color.set(value.color)
      report.push(`light:${key}=ok`)
    }
    for (const [name, props] of Object.entries(settings.materials ?? {})) {
      if (props.emissiveIntensity !== undefined) {
        report.push(`${name}.emissiveIntensity=${debug?.setMaterial?.([name], 'emissiveIntensity', props.emissiveIntensity)}`)
      }
      if (props.emissive !== undefined) {
        report.push(`${name}.emissive=${debug?.setEmissive?.([name], props.emissive)}`)
      }
      for (const [uniform, value] of Object.entries(props.uniforms ?? {})) {
        report.push(`${name}.${uniform}=${debug?.setUniformOn?.([name], uniform, value)}`)
      }
    }
    if (settings.exposure !== undefined && debug?.renderer?.()) {
      debug.renderer().toneMappingExposure = settings.exposure
      report.push(`exposure=${settings.exposure}`)
    }
    if (settings.bloom !== undefined) {
      const pass = debug?.bloomPass?.()
      if (!pass) {
        report.push('bloom=missing')
      }
      else {
        if (settings.bloom.enabled !== undefined)
          pass.enabled = settings.bloom.enabled
        if (settings.bloom.strength !== undefined)
          pass.strength = settings.bloom.strength
        if (settings.bloom.threshold !== undefined)
          pass.threshold = settings.bloom.threshold
        if (settings.bloom.radius !== undefined)
          pass.radius = settings.bloom.radius
        report.push(`bloom=strength:${pass.strength} threshold:${pass.threshold} enabled:${pass.enabled}`)
      }
    }
    return report
  }, variant)
  await page.waitForTimeout(1400)
  const file = path.join(outDir, `${index}-${variant.name ?? 'variant'}.png`)
  await canvas.screenshot({ path: file })
  console.log(`VARIANT ${file} ${applied.join(' ')}`)
}
console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
