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

const url = process.argv[2] || 'http://localhost:5199'
const directory = 'docs/yxz-audit/defect-uv'
mkdirSync(directory, { recursive: true })

const browser = await chromium.launch({
  executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe'),
})
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${url}/yxz-avatar`)
  await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
  await page.getByRole('button', { name: '暂停', exact: true }).click()

  const result = await page.evaluate(() => {
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
      const entry = { pixels: context.getImageData(0, 0, canvas.width, canvas.height).data, width: image.width, height: image.height, flipY: material.map.flipY }
      cache.set(material, entry)
      return entry
    }
    const pick = (x, y) => {
      rays.setFromCamera(new THREE.Vector2((x - bounds.x) / bounds.width * 2 - 1, 1 - (y - bounds.y) / bounds.height * 2), camera)
      const hit = rays.intersectObject(scene, true)[0]
      if (!hit) return { x, y, hit: null }
      const material = Array.isArray(hit.object.material) ? hit.object.material[hit.face.materialIndex] : hit.object.material
      const atlas = atlasOf(material)
      let colour = null
      if (atlas && hit.uv) {
        const row = Math.floor(hit.uv.y * (atlas.height - 1))
        const column = Math.floor(hit.uv.x * (atlas.width - 1))
        const offset = (row * atlas.width + column) * 4
        colour = Array.from(atlas.pixels.slice(offset, offset + 3))
      }
      return {
        x,
        y,
        mesh: hit.object.name,
        uv: hit.uv ? hit.uv.toArray() : null,
        colour,
        pixel: atlas ? [Math.floor(hit.uv.x * (atlas.width - 1)), Math.floor(hit.uv.y * (atlas.height - 1))] : null,
      }
    }
    const grid = []
    for (let y = 240; y <= 360; y += 6) {
      for (let x = 520; x <= 860; x += 6) grid.push(pick(x, y))
    }
    return { grid }
  })

  writeFileSync(`${directory}/grid.json`, JSON.stringify(result.grid, null, 1))
  await page.screenshot({ path: `${directory}/page.png` })
  const white = result.grid.filter(entry => entry.colour && entry.colour[0] > 120 && entry.colour[1] > 120 && entry.colour[2] > 120)
  console.log('samples', result.grid.length, 'bright', white.length)
  console.log(white.slice(0, 40))
}
finally {
  await browser.close()
}
