/** Close-ups of the live model, from the page's own camera.
 *
 * The whole-figure captures answer "does it read as solid" and nothing
 * else.  A defect worth naming is a few millimetres across, so it has
 * to be looked at from close enough that its own shape is the subject
 * -- and it has to be looked at through the page's own renderer, with
 * its own lights, its own outline and its own material settings, or the
 * answer is about the capture rather than about the character.
 *
 * Usage: node scripts/probe_yxz_closeup.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-diag/closeup'
const query = process.argv[4] ?? process.env.YXZ_QUERY ?? ''

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
// The character's living layer keeps moving the head whatever the mixer
// is doing, so the pose is paused before anything is looked at: a
// capture and a texel pick taken a second apart would be looking at
// two different places on the model, and the close-ups would not match
// the atlas coordinates the probe reports.
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
await page.waitForTimeout(1200)

// The camera is put where the head is and pulled in until the head fills
// the frame.  The head's own place is measured from the model rather than
// guessed: the eye caps are separate objects and they sit on the face.
const shots = [
  { name: 'head', eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  { name: 'crown', eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  { name: 'halo', eye: [0, 3.3, 3.4], look: [0, 3.5, 0] },
  { name: 'body', eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
]

mkdirSync(outDir, { recursive: true })
const canvas = page.locator('.yxz-real-model-canvas canvas')
for (const shot of shots) {
  await page.evaluate(([eye, look]) => {
    const debug = window.__yxzDebug
    const camera = debug?.camera?.()
    if (!camera)
      return
    camera.position.set(eye[0], eye[1], eye[2])
    camera.lookAt(look[0], look[1], look[2])
    camera.updateProjectionMatrix()
  }, [shot.eye, shot.look])
  await page.waitForTimeout(1400)
  const file = path.join(outDir, `${shot.name}.png`)
  await canvas.screenshot({ path: file })
  console.log(`SHOT ${file}`)
}

console.log(`ERRORS ${JSON.stringify(errors)}`)
await browser.close()
