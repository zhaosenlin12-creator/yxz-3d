import { mkdir } from 'node:fs/promises'
import { readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).find(entry => entry.startsWith('playwright@'))
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function chromiumPath() {
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/finish-ab-r104')
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: chromiumPath(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 } })
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
await page.waitForTimeout(1000)

const canvas = page.locator('.yxz-real-model-canvas canvas')
const shots = [
  ['front', [0, 2.52, 3.1], [0, 2.45, 0.5]],
  ['oblique', [1.05, 2.55, 2.9], [0, 2.45, 0.45]],
  ['crown', [0.4, 3.4, 2.6], [0, 2.9, 0.4]],
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

async function capture(prefix) {
  for (const [name, eye, look] of shots) {
    await aim(eye, look)
    await canvas.screenshot({ path: path.join(outDir, `${prefix}-${name}.png`) })
  }
}

await capture('baseline')

await page.evaluate(() => {
  const debug = window.__yxzDebug
  const renderer = debug?.renderer?.()
  const outline = debug?.outlinePass?.()
  const bloom = debug?.bloomPass?.()
  if (renderer)
    renderer.toneMappingExposure = 0.92
  if (outline) {
    outline.uniforms.uLine.value = 0.18
    outline.uniforms.uSkirt.value = 0.24
  }
  if (bloom) {
    bloom.strength = 0.55
    bloom.radius = 0.45
  }
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh || !object.name.startsWith('tripo_'))
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      const uniforms = material.uniforms ?? {}
      uniforms.parametricRimColorFactor?.value?.setRGB?.(0.14, 0.20, 0.29)
      if (uniforms.rimLightingMixFactor)
        uniforms.rimLightingMixFactor.value = 0.035
      if (uniforms.parametricRimFresnelPowerFactor)
        uniforms.parametricRimFresnelPowerFactor.value = 4.1
      uniforms.shadeColorFactor?.value?.setRGB?.(0.40, 0.47, 0.60)
      if (uniforms.shadingToonyFactor)
        uniforms.shadingToonyFactor.value = 0.36
    }
  })
  for (const name of ['key', 'rim', 'fill', 'frontal', 'bounce']) {
    const light = window.__yxzDebug?.scene?.()?.getObjectByName?.(name)
    if (light && 'intensity' in light) {
      if (name === 'key')
        light.intensity = 1.62
      else if (name === 'rim')
        light.intensity = 0.55
      else if (name === 'fill')
        light.intensity = 0.18
      else if (name === 'frontal')
        light.intensity = 0.15
      else if (name === 'bounce')
        light.intensity = 0.22
    }
  }
})
await capture('natural')

await browser.close()
console.log('OUT', outDir)
