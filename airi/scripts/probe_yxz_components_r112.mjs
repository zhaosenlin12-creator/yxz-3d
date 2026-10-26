import { mkdir, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
let playwright
try {
  playwright = await import(pathToFileURL(require.resolve('playwright')).href)
}
catch {
  const store = path.resolve('node_modules/.pnpm')
  const match = (await readdir(store)).filter(entry => entry.startsWith('playwright@')).sort().at(-1)
  playwright = await import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

const localAppData = process.env.LOCALAPPDATA
const browsers = await readdir(path.join(localAppData, 'ms-playwright'))
const revision = browsers
  .filter(entry => entry.startsWith('chromium-'))
  .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
const executablePath = process.env.YXZ_CHROMIUM_PATH
  ?? path.join(localAppData, 'ms-playwright', revision, 'chrome-win64', 'chrome.exe')
const outDir = 'docs/yxz-audit/components-r112'
await mkdir(outDir, { recursive: true })

const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})

try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:5199/yxz-avatar', { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )

  const inventory = await page.evaluate(() => {
    const scene = window.__yxzVrm?.scene
    const rows = []
    scene?.traverse((object) => {
      if (object.isMesh) {
        rows.push({
          name: object.name,
          visible: object.visible,
          vertices: object.geometry.attributes.position?.count ?? 0,
          triangles: object.geometry.index
            ? object.geometry.index.count / 3
            : (object.geometry.attributes.position?.count ?? 0) / 3,
        })
      }
    })
    return rows
  })

  await page.evaluate(() => {
    const canvas = document.querySelector('.yxz-real-model-canvas canvas')
    for (const element of document.querySelectorAll('body *')) {
      if (element === canvas || element.contains(canvas))
        continue
      element.style.setProperty('display', 'none', 'important')
    }
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)

    const camera = window.__yxzDebug?.camera?.()
    if (camera) {
      camera.position.set(0, 2.5, 1.95)
      camera.lookAt(0, 2.42, 0.3)
      camera.updateProjectionMatrix()
      camera.updateMatrixWorld(true)
    }
  })
  await page.waitForTimeout(2500)

  const variants = [
    'baseline',
    'no-mouth-plate',
    'no-mouth-cavity',
    'no-mouth-overlays',
    'no-eye-overlays',
    'main-scan-only',
  ]
  const canvas = page.locator('.yxz-real-model-canvas canvas')

  for (const name of variants) {
    await page.evaluate((name) => {
      const scene = window.__yxzVrm?.scene
      if (!scene)
        return
      scene.traverse((object) => {
        if (object.isMesh)
          object.visible = true
      })
      if (name === 'main-scan-only') {
        scene.traverse((object) => {
          if (object.isMesh && object.name.startsWith('YXZ_'))
            object.visible = false
        })
      }
      else if (name !== 'baseline') {
        scene.traverse((object) => {
          if (object.isMesh && object.name.startsWith('YXZ_'))
            object.visible = true
        })
      }
    }, name)

    if (name !== 'baseline') {
      await page.evaluate((name) => {
        const scene = window.__yxzVrm?.scene
        if (!scene || name === 'main-scan-only')
          return
        const configure = {
          'no-mouth-plate': object => object.name === 'YXZ_Mouth',
          'no-mouth-cavity': object => object.name === 'YXZ_MouthCavity',
          'no-mouth-overlays': object => object.name === 'YXZ_Mouth' || object.name === 'YXZ_MouthCavity',
          'no-eye-overlays': object => /^YXZ_(Eye|Iris|Sclera|Socket)/.test(object.name),
        }[name]
        if (!configure)
          return
        scene.traverse((object) => {
          if (object.isMesh && configure(object))
            object.visible = false
        })
      }, name)
    }

    await page.waitForTimeout(500)
    await canvas.screenshot({ path: path.join(outDir, `${name}.png`) })
    console.log('SHOT', name)
  }

  await import('node:fs/promises').then(({ writeFile }) =>
    writeFile(path.join(outDir, 'inventory.json'), JSON.stringify(inventory, null, 2)))
  console.log('PAGE_ERRORS', JSON.stringify(errors))
  console.log('OUT', outDir)
}
finally {
  await browser.close()
}
