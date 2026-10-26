/**
 * Map every visible defect on the face to its place in the base-colour
 * atlas, by raycasting the live page and reading the texel that each
 * visible pixel samples.
 *
 * The point is to stop guessing.  Earlier repairs went wrong because the
 * place a mark sits on screen and the place it sits in the texture are
 * not the same numbers, and because two different things can look like
 * the same mark.  This raycasts a grid over the head, records the atlas
 * colour of every hit, and reports the runs of pixels whose colour is
 * not the local majority -- which is what a defect is, in a picture:
 * a region that does not belong to the surface around it.
 */

import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const store = path.resolve('node_modules/.pnpm')
const playwrightEntry = readdirSync(store).find(name => name.startsWith('playwright@'))
const { chromium } = require(path.join(store, playwrightEntry, 'node_modules/playwright'))
const revision = readdirSync(path.join(process.env.LOCALAPPDATA, 'ms-playwright'))
  .filter(name => name.startsWith('chromium-'))
  .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))[0]
const executablePath = path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe')

const outDir = 'docs/yxz-audit/surface-r72'
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch({ executablePath })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto('http://127.0.0.1:5199/yxz-avatar', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.evaluate(() => {
    const debug = window.__yxzDebug
    debug.snap('YXZ_Idle', 0)
    debug.scene().updateMatrixWorld(true)
  })

  const grid = await page.evaluate(() => {
    const debug = window.__yxzDebug
    const THREE = debug.three
    const scene = window.__yxzVrm.scene
    const camera = debug.camera()
    camera.updateMatrixWorld(true)
    const bounds = debug.renderer().domElement.getBoundingClientRect()
    const rays = new THREE.Raycaster()
    // The atlas is read once.  Reading it per sample means drawing a
    // 4096-square canvas several thousand times, which takes minutes.
    const images = new Map()
    const samples = []
    for (let y = 190; y <= 420; y += 4) {
      for (let x = 460; x <= 780; x += 4) {
        rays.setFromCamera(
          new THREE.Vector2((x - bounds.x) / bounds.width * 2 - 1, 1 - (y - bounds.y) / bounds.height * 2),
          camera,
        )
        const hit = rays.intersectObject(scene, true).find(item => item.object.name.startsWith('tripo_'))
        if (!hit || !hit.uv)
          continue
        const material = Array.isArray(hit.object.material)
          ? hit.object.material[hit.face.materialIndex]
          : hit.object.material
        const image = material.map?.image
        if (!image)
          continue
        let data = images.get(image)
        if (!data) {
          const canvas = document.createElement('canvas')
          canvas.width = image.width
          canvas.height = image.height
          const ctx = canvas.getContext('2d')
          ctx.drawImage(image, 0, 0)
          data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
          images.set(image, data)
        }
        // The texture is loaded with flipY off, so the image's own first
        // row is v = 0 and the row is measured from the top.
        const column = Math.min(image.width - 1, Math.max(0, Math.floor(hit.uv.x * image.width)))
        const row = Math.min(image.height - 1, Math.max(0, Math.floor(hit.uv.y * image.height)))
        const offset = (row * image.width + column) * 4
        samples.push({
          x,
          y,
          u: hit.uv.x,
          v: hit.uv.y,
          column,
          row,
          colour: [data[offset], data[offset + 1], data[offset + 2]],
        })
      }
    }
    return samples
  })

  // Group the samples by their atlas texel, so a defect that covers many
  // screen pixels is reported once, with the screen area it covers.
  const byTexel = new Map()
  for (const sample of grid) {
    const key = `${sample.column}:${sample.row}`
    const entry = byTexel.get(key)
    if (entry) {
      entry.count += 1
      entry.screen.push([sample.x, sample.y])
    }
    else {
      byTexel.set(key, { column: sample.column, row: sample.row, colour: sample.colour, count: 1, screen: [[sample.x, sample.y]] })
    }
  }

  // The surface colour around a texel is the colour of the texels near
  // it in the atlas that the face actually samples.  A texel whose colour
  // is far from all of them is a mark that is not part of the surface.
  const neighbours = new Map()
  for (const entry of byTexel.values()) {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) {
        const key = `${entry.column + dx}:${entry.row + dy}`
        if (key === `${entry.column}:${entry.row}`)
          continue
        const other = byTexel.get(key)
        if (other)
          neighbours.set(entry.column + ',' + entry.row, (neighbours.get(entry.column + ',' + entry.row) || []).concat(other.colour))
      }
    }
  }

  const marks = []
  for (const entry of byTexel.values()) {
    const around = neighbours.get(`${entry.column},${entry.row}`)
    if (!around || around.length < 4)
      continue
    const mean = [0, 1, 2].map(axis => around.reduce((sum, colour) => sum + colour[axis], 0) / around.length)
    const distance = Math.max(...entry.colour.map((value, axis) => Math.abs(value - mean[axis])))
    if (distance < 26)
      continue
    marks.push({
      column: entry.column,
      row: entry.row,
      colour: entry.colour,
      surround: mean.map(value => Math.round(value)),
      distance: Math.round(distance),
      screenPixels: entry.count,
      screen: entry.screen,
    })
  }

  const summary = {
    gridPoints: grid.length,
    texels: byTexel.size,
    marks: marks.length,
    // The marks that cover the most screen, which is what the viewer sees.
    worst: marks.sort((a, b) => b.screenPixels - a.screenPixels).slice(0, 40).map(mark => ({
      column: mark.column,
      row: mark.row,
      colour: mark.colour,
      surround: mark.surround,
      distance: mark.distance,
      screenPixels: mark.screenPixels,
      screenBox: [
        Math.min(...mark.screen.map(point => point[0])),
        Math.min(...mark.screen.map(point => point[1])),
        Math.max(...mark.screen.map(point => point[0])),
        Math.max(...mark.screen.map(point => point[1])),
      ],
    })),
  }
  writeFileSync(`${outDir}/atlas-defects.json`, JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary, null, 2))
}
finally {
  await browser.close()
}
