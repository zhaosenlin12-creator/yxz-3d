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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/side-ab-r104')
await mkdir(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: chromiumPath(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 } })
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
await page.waitForTimeout(1000)

const canvas = page.locator('.yxz-real-model-canvas canvas')
const THREE = await page.evaluate(() => ({
  front: 0,
  double: 2,
}))

for (const side of [['front', THREE.front], ['double', THREE.double]]) {
  await page.evaluate((sideValue) => {
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh || !object.name.startsWith('tripo_'))
        return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      for (const material of list)
        material.side = sideValue
    })
    const pass = window.__yxzDebug?.outlinePass?.()
    if (pass)
      pass.enabled = false
  }, side[1])
  for (const [name, eye, look] of [
    ['front', [0, 2.52, 3.1], [0, 2.45, 0.5]],
    ['oblique', [1.05, 2.55, 2.9], [0, 2.45, 0.45]],
  ]) {
    await page.evaluate(([eyeValue, lookValue]) => {
      const camera = window.__yxzDebug?.camera?.()
      camera.position.set(...eyeValue)
      camera.lookAt(...lookValue)
      camera.updateProjectionMatrix()
    }, [eye, look])
    await page.waitForTimeout(700)
    await canvas.screenshot({ path: path.join(outDir, `${side[0]}-${name}.png`) })
  }
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
