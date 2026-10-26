/** Where do the black lines on the crown come from?
 *
 * The crown of the helmet is covered in thin black scribbles that read as
 * shattered glass, and three different things could put them there: a hole
 * in the mesh, a shadow, or the outline pass inking an interior edge.  The
 * model is watertight (the hole probe finds no boundary edges at all), so
 * the first is already out -- which leaves the other two, and they look
 * completely different on screen and are fixed in completely different
 * places.  So the crown is photographed five times, changing one thing at
 * a time, and the pictures are compared.
 *
 * Usage: node scripts/probe_yxz_crown.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-diag/crown'

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
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  const debug = window.__yxzDebug
  const camera = debug?.camera?.()
  if (camera) {
    camera.position.set(0.4, 3.4, 2.6)
    camera.lookAt(0, 2.9, 0.4)
    camera.updateProjectionMatrix()
  }
})
await page.waitForTimeout(2000)

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')

// Each step changes one thing and takes the picture, so the differences
// between the pictures say which change was responsible.
const steps = [
  {
    name: '00-base',
    apply: '() => {}',
  },
  {
    name: '01-no-outline',
    apply: `(debug) => {
      const pass = debug.outlinePass()
      if (pass)
        pass.enabled = false
    }`,
  },
  {
    name: '02-no-bloom',
    apply: `(debug) => {
      const pass = debug.bloomPass()
      if (pass)
        pass.enabled = false
    }`,
  },
  {
    name: '03-no-shadow',
    apply: `(debug) => {
      debug.scene()?.traverse((object) => {
        if (object.isLight)
          object.castShadow = false
      })
      debug.renderer()?.shadowMap?.enabled = false
    }`,
  },
  {
    // Every surface in one flat magenta.  Whatever the shading was doing
    // is gone, so what is left is the shape of the mesh: a gap in it shows
    // the page through the canvas, and a surface shows as magenta.
    name: '04-flat-magenta',
    apply: `(debug) => {
      const three = debug.three
      debug.scene()?.traverse((object) => {
        if (!object.isMesh)
          return
        object.material = new three.MeshBasicMaterial({
          color: 0xff22aa,
          side: three.FrontSide,
        })
      })
    }`,
  },
]

for (const step of steps) {
  const applied = await page.evaluate(
    (source) => {
      // eslint-disable-next-line no-new-func
      const fn = new Function(`return (${source})`)()
      fn(window.__yxzDebug)
      return 'ok'
    },
    step.apply,
  ).catch((error) => `error ${error.message}`)
  if (applied !== 'ok') {
    console.log(`SKIP ${step.name} (${applied})`)
    continue
  }
  await page.waitForTimeout(1200)
  const file = path.join(outDir, `${step.name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
