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
const browser = await chromium.launch({
  executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe'),
})
const directory = 'docs/yxz-audit/surface-r71'
mkdirSync(directory, { recursive: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto('http://localhost:5199/yxz-avatar')
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
    const imageData = new Map()
    const meshes = []
    scene.traverse(object => {
      if (object.isMesh)
        meshes.push({ name: object.name, vertices: object.geometry.attributes.position.count, triangles: object.geometry.index?.count / 3, materials: (Array.isArray(object.material) ? object.material : [object.material]).map(m => m.name) })
    })
    const samples = [[600, 280], [600, 295], [575, 280], [625, 280], [550, 280], [550, 420], [600, 425], [470, 204], [700, 204], [600, 210]]
    const picks = samples.map(([x, y]) => {
      rays.setFromCamera(new THREE.Vector2((x - bounds.x) / bounds.width * 2 - 1, 1 - (y - bounds.y) / bounds.height * 2), camera)
      const hits = rays.intersectObject(scene, true).slice(0, 5).map(hit => {
        const m = Array.isArray(hit.object.material) ? hit.object.material[hit.face.materialIndex] : hit.object.material
        let colors = null
        const image = m.map?.image
        if (image && hit.uv) {
          if (!imageData.has(image)) {
            const c = document.createElement('canvas')
            c.width = image.width
            c.height = image.height
            const ctx = c.getContext('2d')
            ctx.drawImage(image, 0, 0)
            imageData.set(image, ctx.getImageData(0, 0, c.width, c.height).data)
          }
          const pixels = imageData.get(image)
          colors = [hit.uv.y, 1 - hit.uv.y].map(v => {
            const offset = (Math.floor(v * (image.height - 1)) * image.width + Math.floor(hit.uv.x * (image.width - 1))) * 4
            return Array.from(pixels.slice(offset, offset + 3))
          })
        }
        return {
          mesh: hit.object.name, material: m.name, face: hit.faceIndex, uv: hit.uv?.toArray(),
          flipY: m.map?.flipY, colors,
          world: hit.point.toArray(),
          local: hit.object.worldToLocal(hit.point.clone()).toArray(),
          distance: hit.distance,
          normal: hit.face.normal.toArray(),
        }
      })
      return { x, y, hits }
    })
    return { meshes, picks }
  })
  writeFileSync(`${directory}/picks.json`, JSON.stringify(result, null, 2))
  await page.screenshot({ path: `${directory}/baseline.png` })
  console.log(result.meshes)
  console.log(result.picks.map(p => ({ x: p.x, y: p.y, ...p.hits[0] })))
}
finally {
  await browser.close()
}
