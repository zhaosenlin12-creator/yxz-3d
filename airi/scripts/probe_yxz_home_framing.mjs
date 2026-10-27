/**
 * Why does the character overflow on the product home page?
 *
 * The scene frames itself from the size of its own canvas, so the
 * question is what the canvas is and where the camera ends up.  This
 * reports both, plus the model's real world bounds, so the two can be
 * compared.
 *
 * Usage:
 *   node scripts/probe_yxz_home_framing.mjs [baseUrl] [route]
 */

import path from 'node:path'
import process from 'node:process'

import { existsSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}

  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
  const match = readdirSync(store)
    .filter(entry => entry.startsWith('playwright@'))
    .sort()
    .at(-1)
  if (!match)
    throw new Error('playwright is not installed')
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const route = process.argv[3] ?? '/'

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => Boolean(document.querySelector('.yxz-real-model-canvas canvas')),
  null,
  { timeout: 180_000 },
)
await page.waitForTimeout(20_000)

const report = await page.evaluate(() => {
  const debug = window.__yxzDebug
  const vrm = window.__yxzVrm
  if (!debug || !vrm)
    return { error: 'no debug handle' }

  const container = document.querySelector('.yxz-real-model-canvas')
  const canvas = container?.querySelector('canvas')
  const camera = debug.camera?.()
  const scene = debug.scene?.()

  const box = canvas?.getBoundingClientRect()
  const containerBox = container?.getBoundingClientRect()

  // The model's world bounds, measured off the scene graph.
  let modelBox = null
  if (scene) {
    const min = { x: Infinity, y: Infinity, z: Infinity }
    const max = { x: -Infinity, y: -Infinity, z: -Infinity }
    scene.traverse((object) => {
      if (!object.isMesh || !object.geometry?.boundingBox)
        object.geometry?.computeBoundingBox?.()
      if (!object.isMesh || !object.geometry?.boundingBox)
        return
      const bb = object.geometry.boundingBox
      min.x = Math.min(min.x, bb.min.x)
      min.y = Math.min(min.y, bb.min.y)
      min.z = Math.min(min.z, bb.min.z)
      max.x = Math.max(max.x, bb.max.x)
      max.y = Math.max(max.y, bb.max.y)
      max.z = Math.max(max.z, bb.max.z)
    })
    modelBox = { min, max }
  }

  const ancestors = []
  let node = container
  while (node && node !== document.body) {
    const style = getComputedStyle(node)
    ancestors.push({
      tag: node.tagName,
      cls: (node.className || '').toString().slice(0, 120),
      rect: (() => {
        const r = node.getBoundingClientRect()
        return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
      })(),
      transform: style.transform,
      zoom: style.zoom,
    })
    node = node.parentElement
  }

  return {
    canvas: {
      css: box ? [Math.round(box.width), Math.round(box.height), Math.round(box.x), Math.round(box.y)] : null,
      buffer: canvas ? [canvas.width, canvas.height] : null,
    },
    container: containerBox
      ? [Math.round(containerBox.width), Math.round(containerBox.height), Math.round(containerBox.x), Math.round(containerBox.y)]
      : null,
    camera: camera
      ? {
          position: camera.position.toArray().map(v => +v.toFixed(3)),
          fov: camera.fov,
          aspect: +camera.aspect.toFixed(3),
          near: camera.near,
          far: camera.far,
        }
      : null,
    modelBox,
    ancestors,
  }
})

console.log(JSON.stringify({ route, report, pageErrors }, null, 2))
await browser.close()
