// Is the white mark on the visor in the texture, or is it light?
//
// The same picture is taken twice: once with the avatar's own material
// and once with a plain unlit material that shows only the base colour
// map.  A mark that is in the texture survives the swap; a mark that is
// a highlight does not.
import { readdirSync } from 'node:fs'
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
const browser = await chromium.launch({
  executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe'),
})
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${url}/yxz-avatar`)
  await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'docs/yxz-audit/defect-map/light-lit.png', clip: { x: 500, y: 240, width: 180, height: 90 } })
  await page.evaluate(() => {
    const THREE = window.__yxzDebug.three
    window.__yxzVrm.scene.traverse((object) => {
      if (!object.isMesh) return
      const list = Array.isArray(object.material) ? object.material : [object.material]
      object.material = list.map((material) => {
        const plain = new THREE.MeshBasicMaterial({
          map: material.map || null,
          color: material.color || 0xffffff,
          transparent: material.transparent,
          opacity: material.opacity,
          side: THREE.FrontSide,
        })
        plain.name = material.name
        return plain
      })
      if (!Array.isArray(object.material)) object.material = object.material[0]
    })
    window.__yxzVrm.scene.updateMatrixWorld(true)
  })
  await page.waitForTimeout(800)
  await page.screenshot({ path: 'docs/yxz-audit/defect-map/light-unlit.png', clip: { x: 500, y: 240, width: 180, height: 90 } })
  console.log('YXZ_LIGHT ok')
}
finally {
  await browser.close()
}
