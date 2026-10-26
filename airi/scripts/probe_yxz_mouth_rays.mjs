/**
 * Whether the mouth is actually closed.
 *
 * A pale line along the lips is either a hole in the geometry or the
 * crease at the edge of the lips catching the light, and the two are
 * told apart by casting a ray at every pixel of the mouth and looking
 * at what it hits.  A ray that hits nothing went through a gap; a ray
 * that hits the lining hit the inside of the mouth.
 *
 * The result is a map of the mouth: which object each pixel belongs
 * to, printed as a grid of letters.
 *
 * Usage: node scripts/probe_yxz_mouth_rays.mjs [baseUrl]
 */

import { readdirSync } from 'node:fs'
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

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.waitForTimeout(1200)

const report = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const camera = debug?.camera?.()
  const scene = debug?.scene?.()
  if (!camera || !scene || !THREE)
    return { error: 'no scene' }
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const rect = canvas.getBoundingClientRect()

  let mouth = null
  scene.traverse((object) => {
    if (object.isMesh && object.name === 'YXZ_Mouth')
      mouth = object
  })
  if (!mouth)
    return { error: 'no mouth' }
  const centre = new THREE.Vector3()
  new THREE.Box3().setFromObject(mouth).getCenter(centre)
  const projected = centre.project(camera)
  const cx = (projected.x * 0.5 + 0.5) * rect.width
  const cy = (-projected.y * 0.5 + 0.5) * rect.height

  const raycaster = new THREE.Raycaster()
  // Only the three pieces that make up the mouth are worth asking
  // about: the face behind, the plate that carries the lips, and the
  // lining behind the opening.  The rest of the character is a closed
  // shell, so a ray that misses all three went through the mouth.
  const targets = []
  scene.traverse((object) => {
    if (object.isMesh && object.visible
      && (object.name === 'YXZ_Mouth'
        || object.name === 'YXZ_MouthCavity'
        || object.name.startsWith('tripo_')))
      targets.push(object)
  })

  const letter = {
    'YXZ_Mouth': 'P',
    'YXZ_MouthCavity': 'C',
  }
  const rows = []
  const hits = []
  const columns = 60
  const rowCount = 22
  for (let row = 0; row < rowCount; row++) {
    let text = ''
    for (let column = 0; column < columns; column++) {
      const x = cx - 45 + column * (90 / columns)
      const y = cy - 14 + row * (28 / rowCount)
      const ndc = new THREE.Vector2(
        (x / rect.width) * 2 - 1,
        -((y / rect.height) * 2 - 1),
      )
      raycaster.setFromCamera(ndc, camera)
      const found = raycaster.intersectObjects(targets, false)
      if (!found.length) {
        text += '.'
        hits.push({ x: +x.toFixed(1), y: +y.toFixed(1), name: null })
        continue
      }
      const name = found[0].object.name
      text += letter[name] ?? (name.startsWith('tripo_') ? 'F' : '?')
      hits.push({ x: +x.toFixed(1), y: +y.toFixed(1), name })
    }
    rows.push(text)
  }
  const gaps = hits.filter(hit => !hit.name)
  return {
    mouth: { cx: +cx.toFixed(1), cy: +cy.toFixed(1) },
    map: rows,
    gapCount: gaps.length,
    gapSamples: gaps.slice(0, 12),
  }
})

console.log(`mouth at ${JSON.stringify(report.mouth)}`)
for (const row of report.map ?? [])
  console.log(row)
console.log(`gaps: ${report.gapCount}`)
console.log(JSON.stringify(report.gapSamples ?? [], null, 1))
await browser.close()
