/** Which piece of the mouth is making the mess?
 *
 * Loads a candidate model, hides one piece of the mouth at a time and
 * takes a close-up of the mouth for each, so the piece that is
 * responsible for an artefact can be seen rather than guessed at.
 *
 *   node scripts/probe_yxz_candidate_parts.mjs <candidate.vrm> <outDir>
 */

import { mkdirSync, readdirSync, readFileSync } from 'node:fs'
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
  const match = readdirSync(store)
    .filter(name => name.startsWith('playwright@'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return import(pathToFileURL(
    path.join(store, match, 'node_modules/playwright/index.js')).href)
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

const candidate = path.resolve(process.argv[2])
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/parts')
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

await page.route('**/*', async (route) => {
  const url = new URL(route.request().url())
  if (
    !url.pathname.endsWith('.vrm')
    || !['fetch', 'xhr'].includes(route.request().resourceType())
  ) {
    await route.continue()
    return
  }
  await route.fulfill({
    status: 200,
    contentType: 'model/gltf-binary',
    body: readFileSync(candidate),
  })
})

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

const canvas = page.locator('.yxz-real-model-canvas canvas')
const VARIANTS = [
  { name: 'all', hide: [] },
  { name: 'no-dish', hide: ['YXZ_MouthCavity'] },
  { name: 'no-plate', hide: ['YXZ_Mouth'] },
  { name: 'only-plate', hide: ['YXZ_MouthCavity'] },
]

for (const variant of VARIANTS) {
  await page.evaluate((hide) => {
    const scene = window.__yxzDebug?.scene?.()
    scene?.traverse((object) => {
      if (!object.isMesh)
        return
      if (object.name === 'YXZ_Mouth' || object.name === 'YXZ_MouthCavity') {
        object.visible = !hide.includes(object.name)
        return
      }
      object.visible = true
    })
  }, variant.hide)
  for (let i = 0; i < 4; i++) {
    await page.evaluate(([point]) => {
      const camera = window.__yxzDebug?.camera?.()
      if (!camera || !point)
        return
      camera.position.set(point[0], point[1], point[2] + 0.95)
      camera.lookAt(point[0], point[1], point[2])
      camera.updateProjectionMatrix()
    }, [anchor])
    await page.waitForTimeout(300)
  }
  await page.waitForTimeout(400)
  const file = path.join(outDir, `${variant.name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file}`)
}

console.log('ERRORS ' + JSON.stringify(errors))
await browser.close()
