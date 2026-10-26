/**
 * Decide whether the speckle band is a rendering artifact or the model.
 *
 * The band survived the rim light being off, a soft terminator, the
 * texture being removed, the outline being switched off, the shadow map
 * being switched off, and the alpha being thresholded.  A Blender render
 * of the same mesh has no band at all, so the model is clean and the
 * three.js pipeline is the suspect.
 *
 * Two questions settle it:
 *
 *   is the band in the beauty pass colour   replacing the outline pass
 *   with a pass-through that writes opaque colour answers this.  If the
 *   band is still there, it is in the colour the renderer produced
 *
 *   does the band depend on the view          the top lip of the visor is
 *   almost edge on from the stage camera, so the band may simply be that
 *   lip seen at a grazing angle.  Moving the camera answers this
 *
 * Usage: node scripts/probe_yxz_band3.mjs [baseUrl] [outDir]
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
  const match = readdirSync(store).filter(e => e.startsWith('sharp@')).sort().at(-1)
  if (!match)
    return null
  const entry = path.join(store, match, 'node_modules', 'sharp', 'lib', 'index.js')
  if (!existsSync(entry))
    return null
  return (await import(pathToFileURL(entry).href)).default
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
const outDir = process.argv[3] ?? 'docs/yxz-band3x'
await mkdirSync(outDir, { recursive: true })

const playwright = await importPlaywright()
const sharp = await importSharp()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const canvas = page.locator('.yxz-real-model-canvas canvas')

async function park() {
  await page.evaluate(() => {
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  await page.waitForTimeout(6000)
}

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (sharp) {
    const { width, height } = await sharp(file).metadata()
    await sharp(file)
      .extract({ left: Math.round(width * 0.30), top: Math.round(height * 0.18), width: Math.round(width * 0.42), height: Math.round(height * 0.22) })
      .resize({ width: 1400, kernel: 'nearest' })
      .toFile(path.join(outDir, `${name}-band.png`))
  }
  console.log('SHOT', name)
}

// The outline pass replaced by a pass-through that keeps the beauty
// colour and writes it out fully opaque.  Whatever the band is, it is
// either in the colour or it is not.
async function opaquePassThrough() {
  await page.evaluate(() => {
    const pass = window.__yxzDebug?.outlinePass?.()
    if (!pass)
      return
    pass.material.fragmentShader = `
      uniform sampler2D tDiffuse;
      varying vec2 vUv;
      void main() {
        vec4 base = texture2D( tDiffuse, vUv );
        gl_FragColor = vec4( base.rgb, 1.0 );
      }
    `
    pass.material.needsUpdate = true
  })
  await page.waitForTimeout(5000)
}

async function moveCamera(position, target) {
  await page.evaluate(({ position, target }) => {
    const camera = window.__yxzDebug?.camera?.()
    if (!camera)
      return
    camera.position.set(position[0], position[1], position[2])
    camera.lookAt(target[0], target[1], target[2])
    camera.updateMatrixWorld()
  }, { position, target })
  await page.waitForTimeout(5000)
}

await park()
await shoot('1-as-is')

await opaquePassThrough()
await shoot('2-opaque-passthrough')

await moveCamera([0, 2.05, 8.8], [0, 2.05, 0])
await shoot('3-camera-level')

await moveCamera([0, 3.6, 8.8], [0, 2.05, 0])
await shoot('4-camera-above')

await moveCamera([2.2, 2.6, 8.2], [0, 2.05, 0])
await shoot('5-camera-side')

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
