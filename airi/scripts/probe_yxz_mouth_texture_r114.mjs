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

const appData = process.env.LOCALAPPDATA
const revisions = await readdir(path.join(appData, 'ms-playwright'))
const chromiumRevision = revisions
  .filter(entry => entry.startsWith('chromium-'))
  .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
const executablePath = process.env.YXZ_CHROMIUM_PATH
  ?? path.join(appData, 'ms-playwright', chromiumRevision, 'chrome-win64', 'chrome.exe')
const outputDirectory = 'docs/yxz-audit/mouth-texture-r114'
await mkdir(outputDirectory, { recursive: true })

const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})

try {
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:5199/yxz-avatar', { waitUntil: 'domcontentloaded', timeout: 120_000 })
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

    const wanted = { eye: [0, 2.50, 1.95], look: [0, 2.42, 0.30] }
    const pin = () => {
      const camera = window.__yxzDebug?.camera?.()
      if (camera) {
        camera.position.set(...wanted.eye)
        camera.lookAt(...wanted.look)
        camera.updateProjectionMatrix()
      }
      requestAnimationFrame(pin)
    }
    requestAnimationFrame(pin)
  })
  await page.waitForTimeout(2500)

  const result = await page.evaluate(() => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzVrm?.scene
    if (!three || !scene)
      return { error: 'scene unavailable' }

    let body
    let mouth
    scene.traverse((object) => {
      if (object.isMesh && object.name.startsWith('tripo_'))
        body = object
      if (object.isMesh && object.name === 'YXZ_Mouth')
        mouth = object
    })
    if (!body || !mouth)
      return { error: 'body or mouth mesh unavailable' }

    scene.updateMatrixWorld(true)
    body.updateMatrixWorld(true)
    mouth.updateMatrixWorld(true)
    const position = mouth.geometry.attributes.position
    const bodyMaterial = Array.isArray(body.material) ? body.material[0] : body.material
    const mouthMaterial = Array.isArray(mouth.material) ? mouth.material[0] : mouth.material
    const before = {
      map: Boolean(mouthMaterial.map),
      color: mouthMaterial.color?.getHexString?.() ?? null,
      uvAttribute: Boolean(mouth.geometry.attributes.uv),
    }
    mouthMaterial.map = bodyMaterial.map
    mouthMaterial.color?.setHex(0xFFFFFF)
    mouthMaterial.needsUpdate = true

    const offsets = [0, 0.004, 0.008, 0.012, 0.016, 0.020]
    const variants = []
    const raycaster = new three.Raycaster()
    const origin = new three.Vector3()
    const direction = new three.Vector3(0, 0, -1)
    const local = new three.Vector3()
    for (const verticalOffset of offsets) {
      const uv = []
      const distances = []
      const misses = []
      for (let index = 0; index < position.count; index++) {
        mouth.getVertexPosition(index, local)
        mouth.localToWorld(local)
        origin.copy(local).add(new three.Vector3(0, verticalOffset, 0.08))
        raycaster.set(origin, direction)
        const hit = raycaster.intersectObject(body, false)[0]
        if (hit?.uv) {
          uv.push(hit.uv.x, hit.uv.y)
          distances.push(hit.distance)
        }
        else {
          uv.push(0.5, 0.5)
          misses.push(index)
        }
      }
      mouth.geometry.setAttribute('uv', new three.Float32BufferAttribute(uv, 2))
      variants.push({
        verticalOffset,
        misses: misses.length,
        missIndices: misses,
        distance: distances.length
          ? {
              min: Math.min(...distances),
              max: Math.max(...distances),
              mean: distances.reduce((sum, value) => sum + value, 0) / distances.length,
            }
          : null,
      })
    }

    return {
      before,
      bodyMap: Boolean(bodyMaterial.map),
      vertices: position.count,
      variants,
    }
  })

  for (const [file, offset] of [
    ['mapped-mouth-000.png', 0],
    ['mapped-mouth-004.png', 0.004],
    ['mapped-mouth-008.png', 0.008],
    ['mapped-mouth-012.png', 0.012],
    ['mapped-mouth-016.png', 0.016],
    ['mapped-mouth-020.png', 0.020],
  ]) {
    await page.evaluate((verticalOffset) => {
      const three = window.__yxzDebug?.three
      const scene = window.__yxzVrm?.scene
      if (!three || !scene)
        return
      let body
      let mouth
      scene.traverse((object) => {
        if (object.isMesh && object.name.startsWith('tripo_'))
          body = object
        if (object.isMesh && object.name === 'YXZ_Mouth')
          mouth = object
      })
      if (!body || !mouth)
        return
      scene.updateMatrixWorld(true)
      const position = mouth.geometry.attributes.position
      const uv = []
      const raycaster = new three.Raycaster()
      const origin = new three.Vector3()
      const direction = new three.Vector3(0, 0, -1)
      const local = new three.Vector3()
      for (let index = 0; index < position.count; index++) {
        mouth.getVertexPosition(index, local)
        mouth.localToWorld(local)
        origin.copy(local).add(new three.Vector3(0, verticalOffset, 0.08))
        raycaster.set(origin, direction)
        const hit = raycaster.intersectObject(body, false)[0]
        uv.push(hit?.uv?.x ?? 0.5, hit?.uv?.y ?? 0.5)
      }
      mouth.geometry.setAttribute('uv', new three.Float32BufferAttribute(uv, 2))
    }, offset)
    await page.waitForTimeout(400)
    await page.locator('.yxz-real-model-canvas canvas').screenshot({
      path: path.join(outputDirectory, file),
    })
  }
  console.log('MOUTH_TEXTURE_TEST', JSON.stringify(result))
  console.log('PAGE_ERRORS', JSON.stringify(errors))
  console.log('OUT', outputDirectory)
}
finally {
  await browser.close()
}
