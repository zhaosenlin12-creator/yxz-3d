/**
 * Where the mouth lands on the screen, in pixels.
 *
 * The stage shot is the only picture that answers "does the user see
 * this", so the defects have to be measured in that picture.  This
 * projects the mouth's own world position through the stage's own
 * camera and prints the pixel, which is all a crop needs.
 *
 * Usage: node scripts/probe_yxz_mouth_px.mjs [baseUrl]
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
await page.waitForTimeout(1500)

const report = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const THREE = debug?.three
  const camera = debug?.camera?.()
  const scene = debug?.scene?.()
  if (!camera || !scene || !THREE)
    return { error: 'no scene' }
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  const rect = canvas.getBoundingClientRect()
  const found = []
  scene.traverse((object) => {
    if (!object.isMesh || !/mouth/i.test(object.name))
      return
    const box = new THREE.Box3().setFromObject(object)
    const centre = new THREE.Vector3()
    box.getCenter(centre)
    const size = new THREE.Vector3()
    box.getSize(size)
    const projected = centre.clone().project(camera)
    found.push({
      name: object.name,
      visible: object.visible,
      centre: centre.toArray().map(v => +v.toFixed(4)),
      size: size.toArray().map(v => +v.toFixed(4)),
      px: [
        Math.round((projected.x * 0.5 + 0.5) * rect.width),
        Math.round((-projected.y * 0.5 + 0.5) * rect.height),
      ],
    })
  })
  return { canvas: { w: rect.width, h: rect.height }, found }
})

console.log(JSON.stringify(report, null, 2))
await browser.close()
