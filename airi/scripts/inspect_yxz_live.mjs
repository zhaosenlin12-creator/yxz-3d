/** Dump the live YXZ eye meshes from the browser for debugging. */

import process from 'node:process'
import { mkdirSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

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

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

function resolveChromiumExecutable() {
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(e => e.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
mkdirSync('docs/yxz-rig-review/browser', { recursive: true })

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.waitForTimeout(2500)

const report = await page.evaluate(() => {
  const vrm = window.__yxzVrm
  if (!vrm)
    return { error: 'no __yxzVrm handle' }

  const wanted = /YXZ_(Iris|Sclera|Socket|EyeShadow)/
  const out = []
  vrm.scene.traverse((object) => {
    if (!object.isMesh || !wanted.test(object.name))
      return
    const geometry = object.geometry
    if (!geometry.boundingBox)
      geometry.computeBoundingBox()
    const box = geometry.boundingBox
    const uv = geometry.attributes.uv

    let uvRange = null
    const uvSample = []
    if (uv) {
      let minU = Infinity
      let maxU = -Infinity
      let minV = Infinity
      let maxV = -Infinity
      for (let i = 0; i < uv.count; i++) {
        const u = uv.getX(i)
        const v = uv.getY(i)
        minU = Math.min(minU, u)
        maxU = Math.max(maxU, u)
        minV = Math.min(minV, v)
        maxV = Math.max(maxV, v)
      }
      uvRange = [minU, maxU, minV, maxV].map(n => +n.toFixed(3))
      for (let i = 0; i < Math.min(uv.count, 6); i++)
        uvSample.push([+uv.getX(i).toFixed(4), +uv.getY(i).toFixed(4)])
    }

    const worldPosition = object.getWorldPosition(new object.position.constructor())
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    out.push({
      name: object.name,
      visible: object.visible,
      renderOrder: object.renderOrder,
      vertexCount: geometry.attributes.position?.count,
      hasUv: Boolean(uv),
      uvRange,
      uvSample,
      size: [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z]
        .map(n => +n.toFixed(5)),
      world: [worldPosition.x, worldPosition.y, worldPosition.z].map(n => +n.toFixed(4)),
      materials: materials.map((m) => ({
        type: m.type,
        isMToon: Boolean(m.isMToonMaterial),
        isOutline: Boolean(m.isOutline),
        color: m.color ? m.color.getHexString() : null,
        hasMap: Boolean(m.map),
        mapImage: m.map?.image ? `${m.map.image.width}x${m.map.image.height}` : null,
        colorSpace: m.map?.colorSpace ?? null,
        transparent: m.transparent,
        opacity: m.opacity,
        side: m.side,
        depthWrite: m.depthWrite,
      })),
    })
  })

  const eyeBones = ['leftEye', 'rightEye'].map((name) => {
    const node = vrm.humanoid?.getNormalizedBoneNode(name)
    if (!node)
      return { name, missing: true }
    const p = node.getWorldPosition(new node.position.constructor())
    return {
      name,
      world: [p.x, p.y, p.z].map(n => +n.toFixed(4)),
      visible: node.visible,
    }
  })

  return { meshes: out, eyeBones }
})

console.log(JSON.stringify(report, null, 2))
await browser.close()
