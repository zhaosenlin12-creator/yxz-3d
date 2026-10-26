/**
 * Find where the dark flecks on the white shell come from.
 *
 * The shell is covered in small dark marks -- on the chest, on the arms,
 * on the legs -- and the character reads as shattered because of them.
 * There are three things that could be drawing them and the page can
 * switch all three off one at a time:
 *
 *   no-outline   the marks are the silhouette pass finding every crack
 *                in the shell and inking round it
 *   front-side   the marks are the inside of the shell showing through
 *                the gaps between the scan's panels
 *   flat-colour  the marks are in the base colour map
 *
 * The last one is the interesting one, because the map can be dumped
 * and looked at directly, while the other two are properties of the
 * render stack.
 *
 * Usage: node scripts/probe_yxz_fleck_ab.mjs [baseUrl] [outDir]
 */

import { existsSync, mkdirSync, readdirSync } from 'node:fs'
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
  if (!existsSync(store))
    throw new Error('no pnpm store')
  const match = readdirSync(store).filter(e => e.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

async function importSharp() {
  const require = createRequire(import.meta.url)
  try {
    return require('sharp')
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    return null
  const match = readdirSync(store).filter(e => e.startsWith('sharp@')).sort().at(-1)
  if (!match)
    return null
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  if (!existsSync(entry))
    return null
  return (await import(pathToFileURL(entry))).default
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
const outDir = process.argv[3] ?? 'docs/yxz-fleck-ab'
mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 })

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
})
await page.waitForTimeout(6000)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/** The chest and the raised arm, where the flecks are densest. */
const FLECK = { left: 330, top: 380, width: 420, height: 300 }

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    await sharp(file)
      .extract(FLECK)
      .resize({ width: 1260, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-fleck.png`))
  }
  console.log('SHOT', name)
}

await shoot('a-baseline')

// The silhouette pass off.  The marks are drawn outside the shell, so if
// they are still there without it, they are not the outline.
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = false
})
await page.waitForTimeout(1500)
await shoot('b-no-outline')

// The outline back, and the shell single sided.  A gap between the
// scan's panels then shows the page through it, in the page's own
// colour, and the marks change from dark to light if they are the
// inside of the shell.
await page.evaluate(() => {
  const pass = window.__yxzDebug?.outlinePass?.()
  if (pass)
    pass.enabled = true
  window.__yxzDebug?.setSide?.(0)
})
await page.waitForTimeout(1500)
await shoot('c-front-side')

await page.evaluate(() => {
  window.__yxzDebug?.setSide?.(2)
})
await page.waitForTimeout(1500)
await shoot('d-back-side')

// The base colour replaced by a flat one.  If the marks are in the map,
// they go with it.
await page.evaluate(() => {
  window.__yxzDebug?.scene?.().traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const item of Array.isArray(material) ? material : [material]) {
      const m = item
      if (!m?.isMToonMaterial)
        continue
      const uniforms = m.userData?.shader?.uniforms ?? m.uniforms
      const map = uniforms?.map?.value
      if (map)
        map.__saved = map.value
    }
  })
})
await page.evaluate(() => {
  window.__yxzDebug?.scene?.().traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const item of Array.isArray(material) ? material : [material]) {
      const m = item
      if (!m?.isMToonMaterial)
        continue
      const uniforms = m.userData?.shader?.uniforms ?? m.uniforms
      const map = uniforms?.map
      if (map?.value) {
        map.value = null
        m.needsUpdate = true
      }
    }
  })
})
await page.waitForTimeout(1500)
await shoot('e-no-map')

// And with the normal map off as well.  A bad normal on a panel seam
// turns a hairline into a dark streak.
await page.evaluate(() => {
  window.__yxzDebug?.scene?.().traverse((object) => {
    const material = object.material
    if (!material)
      return
    for (const item of Array.isArray(material) ? material : [material]) {
      const m = item
      if (!m?.isMToonMaterial)
        continue
      const uniforms = m.userData?.shader?.uniforms ?? m.uniforms
      const normal = uniforms?.normalMap
      if (normal?.value) {
        normal.value = null
        m.needsUpdate = true
      }
    }
  })
})
await page.waitForTimeout(1500)
await shoot('f-no-normal')

console.log('PAGE_ERRORS', JSON.stringify(errors))
await browser.close()
