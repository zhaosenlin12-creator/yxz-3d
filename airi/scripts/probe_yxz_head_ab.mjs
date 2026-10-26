/**
 * The whole head, from a few angles, with the render stack toggled.
 *
 * The mouth close-up finds the mouth.  This finds everything else: the
 * visor edge, the crown, the seam under the jaw -- the places where a
 * mark might be drawn by the outline pass rather than by the model.
 *
 * Usage:
 *   node scripts/probe_yxz_head_ab.mjs [baseUrl] [outDir]
 */

import { mkdirSync, readdirSync } from 'node:fs'
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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/head-ab')
const only = process.argv[4] ? process.argv[4].split(',') : null
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 1000 }, deviceScaleFactor: 1 })
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
async function aim(offset) {
  for (let i = 0; i < 4; i++) {
    await page.evaluate(([point, move]) => {
      const camera = window.__yxzDebug?.camera?.()
      if (!camera || !point)
        return
      camera.position.set(
        point[0] + move[0],
        point[1] + move[1],
        point[2] + move[2],
      )
      camera.lookAt(point[0], point[1] + 0.06, point[2])
      camera.updateProjectionMatrix()
    }, [anchor, offset])
    await page.waitForTimeout(320)
  }
}

const canvas = page.locator('.yxz-real-model-canvas canvas')

const VIEWS = {
  front: [0, 0.04, 1.75],
  'three-quarter': [1.05, 0.30, 1.55],
  'left': [-1.25, 0.28, 1.35],
  'high': [0.35, 1.05, 1.45],
}

const STACKS = {
  all: () => {},
  'no-outline': () => {
    const pass = window.__yxzDebug?.outlinePass?.()
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
  'no-shadow': () => {
    window.__yxzDebug?.scene?.().traverse((object) => {
      if (object.isDirectionalLight)
        object.castShadow = false
    })
  },
  'front-side': () => {
    const three = window.__yxzDebug?.three
    window.__yxzDebug?.scene?.().traverse((object) => {
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (!m?.isMToonMaterial)
          continue
        m.side = three.FrontSide
        m.needsUpdate = true
      }
    })
  },
}

for (const [stack, apply] of Object.entries(STACKS)) {
  if (only && !only.includes(stack))
    continue
  await page.evaluate(() => {
    const pass = window.__yxzDebug?.outlinePass?.()
    if (pass)
      pass.enabled = true
    window.__yxzDebug?.scene?.().traverse((object) => {
      if (object.isDirectionalLight)
        object.castShadow = true
    })
    const three = window.__yxzDebug?.three
    window.__yxzDebug?.scene?.().traverse((object) => {
      const material = object.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (m?.isMToonMaterial) {
          m.side = three.DoubleSide
          m.needsUpdate = true
        }
      }
    })
  })
  await page.evaluate(apply)
  for (const [view, offset] of Object.entries(VIEWS)) {
    await aim(offset)
    const file = path.join(outDir, `${stack}-${view}.png`)
    await canvas.screenshot({ path: file })
    console.log('SHOT ' + file)
  }
}

console.log('ERRORS ' + JSON.stringify(errors))
await browser.close()
