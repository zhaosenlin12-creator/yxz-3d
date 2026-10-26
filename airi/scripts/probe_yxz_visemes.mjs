/**
 * The mouth, under the expressions that make it speak.
 *
 * The plate was rebuilt as a piece of the face's own surface, so the
 * thing that has to be checked is whether the visemes still move it:
 * a plate that is welded to the face and does not move is a face that
 * cannot talk.
 *
 * Usage:
 *   node scripts/probe_yxz_visemes.mjs [baseUrl] [outDir]
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
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/visemes')
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
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

async function aim() {
  for (let i = 0; i < 4; i++) {
    await page.evaluate(([point]) => {
      const camera = window.__yxzDebug?.camera?.()
      if (!camera || !point)
        return
      camera.position.set(point[0], point[1], point[2] + 0.95)
      camera.lookAt(point[0], point[1], point[2])
      camera.updateProjectionMatrix()
    }, [anchor])
    await page.waitForTimeout(320)
  }
}

const canvas = page.locator('.yxz-real-model-canvas canvas')
const SHAPES = ['neutral', 'aa', 'ih', 'ou', 'ee']

for (const shape of SHAPES) {
  const active = await page.evaluate(([shape]) => {
    const manager = window.__yxzVrm?.expressionManager
    if (!manager)
      return 0
    // The animation loop writes every viseme back on every frame, so a
    // value set from outside is gone before the next picture.  The
    // shape has to be pinned inside the setter instead.
    if (!manager.__yxzPinned) {
      manager.__yxzPinned = true
      const original = manager.setValue.bind(manager)
      manager.setValue = (name, value) => {
        if (['aa', 'ih', 'ou', 'ee'].includes(name))
          return original(name, name === manager.__yxzShape ? 1 : 0)
        return original(name, value)
      }
    }
    manager.__yxzShape = shape
    for (const name of ['aa', 'ih', 'ou', 'ee']) {
      manager.setValue(name, shape === name ? 1 : 0)
    }
    return ['aa', 'ih', 'ou', 'ee']
      .map(name => manager.getValue(name) ?? 0)
      .filter(value => value > 0).length
  }, [shape])
  await page.waitForTimeout(600)
  await aim()
  const file = path.join(outDir, `${shape}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file} active=${active}`)
}

console.log('ERRORS ' + JSON.stringify(errors))
await browser.close()
