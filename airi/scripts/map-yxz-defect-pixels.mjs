// Map a screen-space rectangle of the running avatar onto the texture atlas,
// so a defect can be repaired on the texels that actually show it.
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const store = path.resolve('node_modules/.pnpm')
const pw = readdirSync(store).find(name => name.startsWith('playwright@'))
const { chromium } = require(path.join(store, pw, 'node_modules/playwright'))
const revision = readdirSync(path.join(process.env.LOCALAPPDATA, 'ms-playwright'))
  .filter(name => /^chromium-\d+$/.test(name))
  .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))[0]

const url = process.argv[2] || 'http://127.0.0.1:5199'
// Each region is name,x0,y0,x1,y1 in the 1440x900 probe viewport.
const regions = process.argv.slice(3).map(text => {
  const [name, x0, y0, x1, y1] = text.split(',')
  return { name, x0: +x0, y0: +y0, x1: +x1, y1: +y1 }
})
if (!regions.length) throw new Error('no regions given')

const directory = 'docs/yxz-audit/defect-map'
mkdirSync(directory, { recursive: true })

const browser = await chromium.launch({
  executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe'),
})
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${url}/yxz-avatar`)
  await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
  await page.getByRole('button', { name: '暂停', exact: true }).click()

  const result = await page.evaluate((regions) => {
    const debug = window.__yxzDebug
    const THREE = debug.three
    const scene = window.__yxzVrm.scene
    debug.snap('YXZ_Idle', 0)
    scene.updateMatrixWorld(true)
    const camera = debug.camera()
    camera.updateMatrixWorld(true)
    const bounds = debug.renderer().domElement.getBoundingClientRect()
    const rays = new THREE.Raycaster()
    const cache = new Map()
    const atlasOf = (material) => {
      if (cache.has(material)) return cache.get(material)
      const image = material.map?.image
      if (!image) return null
      const canvas = document.createElement('canvas')
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0)
      const entry = { pixels: context.getImageData(0, 0, canvas.width, canvas.height).data, width: image.width, height: image.height }
      cache.set(material, entry)
      return entry
    }
    const pick = (x, y) => {
      rays.setFromCamera(new THREE.Vector2((x - bounds.x) / bounds.width * 2 - 1, 1 - (y - bounds.y) / bounds.height * 2), camera)
      const hit = rays.intersectObject(scene, true)[0]
      if (!hit) return null
      const material = Array.isArray(hit.object.material) ? hit.object.material[hit.face.materialIndex] : hit.object.material
      const atlas = atlasOf(material)
      if (!atlas || !hit.uv) return { x, y, mesh: hit.object.name }
      const column = Math.floor(hit.uv.x * (atlas.width - 1))
      const row = Math.floor(hit.uv.y * (atlas.height - 1))
      const offset = (row * atlas.width + column) * 4
      return {
        x,
        y,
        mesh: hit.object.name,
        texel: [column, row],
        colour: Array.from(atlas.pixels.slice(offset, offset + 3)),
        local: hit.object.worldToLocal(hit.point.clone()).toArray(),
        normal: hit.face.normal.toArray(),
      }
    }
    const out = {}
    for (const region of regions) {
      const samples = []
      for (let y = region.y0; y <= region.y1; y += 2) {
        for (let x = region.x0; x <= region.x1; x += 2) {
          const hit = pick(x, y)
          if (hit) samples.push(hit)
        }
      }
      out[region.name] = samples
    }
    return out
  }, regions)

  writeFileSync(`${directory}/map.json`, JSON.stringify(result))
  for (const [name, samples] of Object.entries(result)) {
    const texels = new Set(samples.filter(s => s.texel).map(s => s.texel.join(',')))
    console.log(name, 'samples', samples.length, 'texels', texels.size)
  }
}
finally {
  await browser.close()
}
