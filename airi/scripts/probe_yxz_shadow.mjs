/** Sweep the shadow settings against the running model.
 *
 * The dot pattern that covers the visor is shadow acne: the shell is one
 * layer thick and nearly edge on to the key light at the top of the
 * visor, so the surface shadows itself.  Every one of the fixes is a
 * number, and the numbers pull against each other -- a bigger bias
 * stops the acne and detaches the shadow from the surface it belongs
 * to -- so they have to be looked at, not reasoned about.
 *
 * Usage: node scripts/probe_yxz_shadow.mjs [baseUrl] [outDir] [shot]
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
  const match = readdirSync(store).filter(e => e.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(e => e.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-diag/shadow'
const shotName = process.argv[4] ?? 'head'

const cameras = {
  head: { eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  crown: { eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  body: { eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
}
const camera = cameras[shotName] ?? cameras.head

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
await page.evaluate(([eye, look]) => {
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
    camera.position.set(eye[0], eye[1], eye[2])
    camera.lookAt(look[0], look[1], look[2])
    camera.updateProjectionMatrix()
  }
}, [camera.eye, camera.look])
await page.waitForTimeout(2000)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')

const steps = [
  { name: '00-base', props: {} },
  {
    name: '01-tight-2048',
    props: {
      mapSize: 2048,
      normalBias: 0.04,
      frustum: [-2.2, 2.2, 3.4, -1.0, 1.0, 14],
    },
  },
  {
    name: '02-tight-2048-normal-010',
    props: {
      mapSize: 2048,
      normalBias: 0.1,
      frustum: [-2.2, 2.2, 3.4, -1.0, 1.0, 14],
    },
  },
  {
    name: '03-no-self-shadow',
    props: { receive: false },
  },
  {
    name: '04-shadowside-back',
    props: { shadowSide: 1, receive: true },
  },
]

for (const step of steps) {
  const applied = await page.evaluate(
    (props) => window.__yxzDebug?.setShadow?.('key', props) ?? 'missing',
    step.props,
  )
  await page.waitForTimeout(1200)
  const file = path.join(outDir, `${step.name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file} ${applied}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
