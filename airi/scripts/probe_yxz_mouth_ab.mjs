/**
 * The mouth plate, against the face it lies on, in one pose.
 *
 * The captures have to come from the same load of the page and the
 * same frame, or the life layer moves the head between them and every
 * difference is the head.
 *
 * Usage:
 *   node scripts/probe_yxz_mouth_ab.mjs [baseUrl] [outDir]
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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/mouth-ab')
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
await page.evaluate(() => {
  // Let the already queued frame run once. The animation loop then sees
  // the replacement and does not queue another frame.
  window.requestAnimationFrame = () => 0
})
await page.waitForTimeout(150)

async function renderOnce() {
  await page.evaluate(() => {
    const debug = window.__yxzDebug
    const renderer = debug?.renderer?.()
    const composer = debug?.composer?.()
    const scene = debug?.scene?.()
    const camera = debug?.camera?.()
    if (composer)
      composer.render(0)
    else if (renderer && scene && camera)
      renderer.render(scene, camera)
  })
  await page.waitForTimeout(50)
}

const anchor = await page.evaluate(() => {
  const scene = window.__yxzDebug?.scene?.()
  let out = null
  scene?.traverse((object) => {
    if (object.name !== 'YXZ_Mouth' || out)
      return
    const position = object.geometry.attributes.position
    const scratch = object.position.clone()
    let x = 0
    let y = 0
    let z = 0
    for (let i = 0; i < position.count; i++) {
      object.getVertexPosition(i, scratch)
      x += scratch.x
      y += scratch.y
      z += scratch.z
    }
    const e = object.matrixWorld.elements
    const lx = x / position.count
    const ly = y / position.count
    const lz = z / position.count
    out = [
      e[0] * lx + e[4] * ly + e[8] * lz + e[12],
      e[1] * lx + e[5] * ly + e[9] * lz + e[13],
      e[2] * lx + e[6] * ly + e[10] * lz + e[14],
    ]
  })
  return out
})
console.log('ANCHOR ' + JSON.stringify(anchor))

// The camera is put back after every wait, because the page's own
// resize handler puts it back where it started.
async function aim() {
  for (let i = 0; i < 4; i++) {
    await page.evaluate(([point]) => {
      const camera = window.__yxzDebug?.camera?.()
      if (!camera || !point)
        return
      camera.position.set(point[0], point[1], point[2] + 1.05)
      camera.lookAt(point[0], point[1], point[2])
      camera.updateProjectionMatrix()
    }, [anchor])
    await page.waitForTimeout(350)
  }
}

await aim()
await renderOnce()
const canvas = page.locator('.yxz-real-model-canvas canvas')

const VARIANTS = {
  'all': () => {},
  'no-plate': () => {
    window.__yxzDebug?.scene?.().traverse((object) => {
      if (object.isMesh && object.name === 'YXZ_Mouth')
        object.visible = false
    })
  },
  'no-dish': () => {
    window.__yxzDebug?.scene?.().traverse((object) => {
      if (object.isMesh && object.name === 'YXZ_MouthCavity')
        object.visible = false
    })
  },
  'no-bloom': () => {
    const pass = window.__yxzDebug?.bloomPass?.()
    if (pass)
      pass.enabled = false
  },
  'no-rim': () => {
    window.__yxzDebug?.scene?.().traverse((object) => {
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        if (m.uniforms?.parametricRimColorFactor)
          m.uniforms.parametricRimColorFactor.value.setRGB(0, 0, 0)
        if (m.uniforms?.rimLightingMixFactor)
          m.uniforms.rimLightingMixFactor.value = 0
      }
    })
  },
  'viseme-aa': () => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return
    for (const name of ['aa', 'ih', 'ou', 'ee'])
      manager.setValue(name, name === 'aa' ? 1 : 0)
    manager.update()
  },
  'viseme-ih': () => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return
    for (const name of ['aa', 'ih', 'ou', 'ee'])
      manager.setValue(name, name === 'ih' ? 1 : 0)
    manager.update()
  },
  'viseme-ou': () => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return
    for (const name of ['aa', 'ih', 'ou', 'ee'])
      manager.setValue(name, name === 'ou' ? 1 : 0)
    manager.update()
  },
  'viseme-ee': () => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return
    for (const name of ['aa', 'ih', 'ou', 'ee'])
      manager.setValue(name, name === 'ee' ? 1 : 0)
    manager.update()
  },
}

// Each variant starts from the same page state: the earlier ones are
// undone before the next one is applied, or every difference is the
// sum of all the differences before it.
const RESET = () => {
  const scene = window.__yxzDebug?.scene?.()
  scene?.traverse((object) => {
    if (object.isMesh)
      object.visible = true
  })
  const manager = window.__yxzVrm?.expressionManager
  if (manager) {
    for (const name of ['aa', 'ih', 'ou', 'ee'])
      manager.setValue(name, 0)
    manager.update()
  }
  const pass = window.__yxzDebug?.bloomPass?.()
  if (pass)
    pass.enabled = true
  scene?.traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const m of Array.isArray(material) ? material : [material]) {
      if (!m?.isMToonMaterial)
        continue
      const saved = m.userData?.__yxzRim
      if (!saved)
        continue
      if (m.uniforms?.parametricRimColorFactor)
        m.uniforms.parametricRimColorFactor.value.setRGB(...saved.rim)
      if (m.uniforms?.rimLightingMixFactor)
        m.uniforms.rimLightingMixFactor.value = saved.mix
    }
  })
}

// The rim the 'no-rim' variant turns off has to be remembered, so that
// it can be put back for the variants that come after it.
await page.evaluate(() => {
  const scene = window.__yxzDebug?.scene?.()
  scene?.traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const m of Array.isArray(material) ? material : [material]) {
      if (!m?.isMToonMaterial)
        continue
      const rim = m.uniforms?.parametricRimColorFactor?.value
      const mix = m.uniforms?.rimLightingMixFactor?.value
      if (!rim || mix === undefined)
        continue
      m.userData = m.userData || {}
      m.userData.__yxzRim = { rim: [rim.r, rim.g, rim.b], mix }
    }
  })
})

for (const [name, apply] of Object.entries(VARIANTS)) {
  await page.evaluate(RESET)
  await page.evaluate(apply)
  await page.evaluate(() => window.__yxzVrm?.expressionManager?.update())
  await renderOnce()
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  console.log('SHOT ' + file)
}

console.log('ERRORS ' + JSON.stringify(errors))
await browser.close()
