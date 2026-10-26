/**
 * Find the bright streaks on the character and identify what draws them.
 *
 * The character reads as "shattered" because a handful of pixels blow out to
 * pure white in places where nothing should be bright at all: a slash across
 * the cheek, a patch next to the mouth, a hairline on the chest.  Those
 * pixels are found here the same way an eye finds them: take the brightest
 * sliver of the frame, then ask the renderer what is actually there.
 *
 * For every cluster the probe raycasts from the camera through the cluster
 * and reports the meshes it passes through, plus the MToon parameters of the
 * material it landed on.  Then it re-renders with the lights, the shadows,
 * the outline and the specular lobe switched off one at a time and counts
 * the blown-out pixels again, so the culprit is identified by elimination
 * rather than by guesswork.
 *
 * Usage: node scripts/probe_yxz_streak.mjs [baseUrl] [outDir]
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
const outDir = process.argv[3] ?? 'docs/yxz-streak'
await mkdirSync(outDir, { recursive: true })

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

// The greeting bubble and the control bar are DOM overlays that sit on top
// of the canvas, and both are white.  They would show up in every pixel
// count, so everything except the canvas itself goes away before anything
// is measured.
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
})

await page.evaluate(() => {
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(6000)

const canvas = page.locator('.yxz-real-model-canvas canvas')

/**
 * Clusters the blown-out pixels of a screenshot.
 *
 * "Blown out" means the pixel is at the very top of the range and carries
 * no colour, so it is a light source rather than a surface: the white body
 * sits a good way below that.  Neighbouring pixels are grouped so a streak
 * comes back as one blob with a position, not as a thousand singletons.
 */
function findHotClusters(pixels, width, height, channels) {
  const luma = new Float32Array(width * height)
  for (let i = 0; i < width * height; i++) {
    const p = i * channels
    const r = pixels[p]
    const g = pixels[p + 1]
    const b = pixels[p + 2]
    luma[i] = 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const sorted = Float32Array.from(luma).sort()
  const cutoff = sorted[Math.floor(sorted.length * 0.9985)]
  const hot = new Uint8Array(width * height)
  for (let i = 0; i < luma.length; i++) {
    const p = i * channels
    const max = Math.max(pixels[p], pixels[p + 1], pixels[p + 2])
    const min = Math.min(pixels[p], pixels[p + 1], pixels[p + 2])
    // Pure white, or so close to it that no other surface in the scene
    // reaches it.
    if (luma[i] >= Math.max(cutoff, 250) && max - min <= 12)
      hot[i] = 1
  }

  const clusters = []
  const seen = new Uint8Array(width * height)
  for (let i = 0; i < hot.length; i++) {
    if (!hot[i] || seen[i])
      continue
    const stack = [i]
    seen[i] = 1
    const members = []
    while (stack.length) {
      const at = stack.pop()
      members.push(at)
      const x = at % width
      const y = Math.floor(at / width)
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = x + dx
        const ny = y + dy
        if (nx < 0 || ny < 0 || nx >= width || ny >= height)
          continue
        const n = ny * width + nx
        if (hot[n] && !seen[n]) {
          seen[n] = 1
          stack.push(n)
        }
      }
    }
    if (members.length < 25)
      continue
    let sumX = 0
    let sumY = 0
    let minX = width
    let maxX = 0
    let minY = height
    let maxY = 0
    for (const at of members) {
      const x = at % width
      const y = Math.floor(at / width)
      sumX += x
      sumY += y
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
    }
    clusters.push({
      area: members.length,
      cx: sumX / members.length,
      cy: sumY / members.length,
      box: [minX, minY, maxX - minX + 1, maxY - minY + 1],
    })
  }
  clusters.sort((a, b) => b.area - a.area)
  return { clusters, cutoff }
}

async function shoot(name) {
  const file = path.join(outDir, `${name}.png`)
  await canvas.screenshot({ path: file })
  if (!sharp)
    return null
  const { data, info } = await sharp(file).raw().toBuffer({ resolveWithObject: true })
  const { clusters, cutoff } = findHotClusters(data, info.width, info.height, info.channels)
  return { file, width: info.width, height: info.height, clusters, cutoff }
}

/** Raycast through a cluster and report everything the ray meets. */
async function probeCluster(cluster, width, height) {
  return page.evaluate(({ cluster, width, height }) => {
    const three = window.__yxzDebug?.three
    const scene = window.__yxzDebug?.scene?.() ?? window.__yxzVrm?.scene
    const camera = window.__yxzDebug?.camera?.()
    if (!three || !scene || !camera)
      return null
    const ndc = new three.Vector2(
      (cluster.cx / width) * 2 - 1,
      -((cluster.cy / height) * 2 - 1),
    )
    const raycaster = new three.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    const hits = raycaster.intersectObject(scene, true)
    return hits.slice(0, 6).map((hit) => {
      const material = hit.object.material
      const single = Array.isArray(material) ? material[0] : material
      return {
        name: hit.object.name || '(unnamed)',
        distance: Number(hit.distance.toFixed(4)),
        point: hit.point.toArray().map(v => Number(v.toFixed(3))),
        material: single?.type ?? null,
        color: single?.color?.getHexString?.() ?? null,
        transparent: single?.transparent ?? null,
        opacity: single?.opacity ?? null,
        side: single?.side ?? null,
        mtoon: single?.isMToonMaterial
          ? {
              shadeColor: single.shadeColorFactor?.getHexString?.() ?? null,
              shadingShift: single.shadingShiftFactor ?? null,
              toony: single.shadingToonyFactor ?? null,
              rimMultiply: single.rimMultiply ?? null,
              rimMix: single.rimLightingMixFactor ?? null,
              paramRim: single.parametricRimColorFactor?.getHexString?.() ?? null,
              fresnel: single.parametricRimFresnelPowerFactor ?? null,
              lift: single.parametricRimLiftFactor ?? null,
              specColor: single.specularColorFactor?.getHexString?.() ?? null,
              spec: single.specularFactor ?? null,
              matcap: single.matcapFactor ?? null,
            }
          : null,
      }
    })
  }, { cluster, width, height })
}

function summarise(result) {
  if (!result)
    return 'no image'
  const total = result.clusters.reduce((sum, c) => sum + c.area, 0)
  const head = result.clusters
    .slice(0, 4)
    .map(c => `[${c.area}px @ ${c.cx.toFixed(0)},${c.cy.toFixed(0)} ${c.box.join('/')}]`)
    .join(' ')
  return `hot=${total} cutoff=${result.cutoff.toFixed(1)} ${head}`
}

console.log('SHOT 1-baseline')
const baseline = await shoot('1-baseline')
console.log(summarise(baseline))

if (baseline) {
  for (const [index, cluster] of baseline.clusters.slice(0, 6).entries()) {
    const hits = await probeCluster(cluster, baseline.width, baseline.height)
    console.log(`CLUSTER ${index} area=${cluster.area} box=${cluster.box.join('/')}`)
    console.log(JSON.stringify(hits))
  }
}

// Switch the scene off one piece at a time and count the blown-out pixels
// again.  Whatever removes the streak is the thing drawing it.
const variants = [
  ['2-no-key', () => {
    window.__yxzDebug?.scene?.().traverse((o) => {
      if (o.isDirectionalLight && o.intensity > 1)
        o.intensity = 0
    })
  }],
  ['3-no-lights', () => {
    window.__yxzDebug?.scene?.().traverse((o) => {
      if (o.isLight)
        o.intensity = 0
    })
  }],
  ['4-no-shadow', () => {
    const renderer = window.__yxzDebug?.renderer?.()
    if (renderer)
      renderer.shadowMap.enabled = false
  }],
  ['5-no-outline', () => {
    const pass = window.__yxzDebug?.outlinePass?.()
    if (pass)
      pass.enabled = false
  }],
  ['6-no-specular', () => {
    window.__yxzDebug?.scene?.().traverse((o) => {
      const material = o.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (m?.isMToonMaterial) {
          m.specularFactor = 0
          m.specularColorFactor?.setRGB(0, 0, 0)
        }
      }
    })
  }],
  ['7-no-rim', () => {
    window.__yxzDebug?.scene?.().traverse((o) => {
      const material = o.material
      if (!material)
        return
      for (const m of Array.isArray(material) ? material : [material]) {
        if (m?.isMToonMaterial) {
          m.rimMultiply = 0
          m.parametricRimColorFactor?.setRGB(0, 0, 0)
        }
      }
    })
  }],
  ['8-low-exposure', () => {
    const renderer = window.__yxzDebug?.renderer?.()
    if (renderer)
      renderer.toneMappingExposure = 0.6
  }],
]

for (const [name, mutate] of variants) {
  await page.evaluate(mutate)
  await page.waitForTimeout(2500)
  const result = await shoot(name)
  console.log(`SHOT ${name}`, summarise(result))
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
console.log('OUT', outDir)
await browser.close()
