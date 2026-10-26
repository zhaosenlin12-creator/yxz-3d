/**
 * The mouth's lip line, against three lip-edge tones.
 *
 * The pale line along the lips is not a highlight and not a crack: it
 * is MToon's shade colour, which is deliberately cool, landing on the
 * crease at the edge of the mouth.  On the rest of the body a crease
 * in the shade reads as form; here it is a two-pixel stripe along the
 * lips, and it reads as a scar.
 *
 * So the plate's shade colour is tried against the live page, and the
 * three results are put side by side at the size the user sees them.
 *
 * Usage: node scripts/probe_yxz_lip_shade.mjs [baseUrl] [outDir]
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

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const outDir = process.argv[3] ?? 'docs/yxz-audit/lip-shade'

const TRIALS = [
  { name: 'a-current', shade: null },
  { name: 'b-warm', shade: [0.55, 0.55, 0.60] },
  { name: 'c-pale', shade: [0.82, 0.82, 0.86] },
]

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
})
await page.waitForTimeout(1500)

const place = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const camera = debug?.camera?.()
  const scene = debug?.scene?.()
  const rect = document.querySelector('.yxz-real-model-canvas canvas').getBoundingClientRect()
  let mouth = null
  scene?.traverse((object) => {
    if (object.isMesh && object.name === 'YXZ_Mouth')
      mouth = object
  })
  if (!mouth || !camera)
    return null
  const centre = new THREE.Vector3()
  new THREE.Box3().setFromObject(mouth).getCenter(centre)
  const projected = centre.project(camera)
  return {
    origin: { x: rect.x, y: rect.y },
    size: { w: rect.width, h: rect.height },
    px: [
      (projected.x * 0.5 + 0.5) * rect.width,
      (-projected.y * 0.5 + 0.5) * rect.height,
    ],
  }
})
console.log(`MOUTH ${JSON.stringify(place)}`)

mkdirSync(outDir, { recursive: true })
for (const trial of TRIALS) {
  await page.evaluate((shade) => {
    const debug = window.__yxzDebug
    const scene = debug?.scene?.()
    scene?.traverse((object) => {
      if (!object.isMesh || object.name !== 'YXZ_MouthPlate')
        return
      const material = object.material
      const uniforms = material?.userData?.shader?.uniforms ?? material?.uniforms
      const uniform = uniforms?.shadeColorFactor
      if (!uniform)
        return
      if (!uniform.__yxzOriginal)
        uniform.__yxzOriginal = uniform.value.clone()
      if (shade)
        uniform.value.setRGB(shade[0], shade[1], shade[2])
      else
        uniform.value.copy(uniform.__yxzOriginal)
    })
  }, trial.shade)
  await page.waitForTimeout(1400)
  const file = path.join(outDir, `${trial.name}.png`)
  await page.screenshot({
    path: file,
    clip: {
      x: place.origin.x,
      y: place.origin.y,
      width: place.size.w,
      height: place.size.h,
    },
  })
  console.log(`SHOT ${file}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
