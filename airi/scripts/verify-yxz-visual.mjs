import assert from 'node:assert/strict'
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const store = path.resolve('node_modules/.pnpm')
function dependency(name) {
  const entry = readdirSync(store).find(item => item.startsWith(`${name}@`))
  return require(path.join(store, entry, 'node_modules', name))
}
const { chromium } = dependency('playwright')
const sharp = dependency('sharp')
const revision = readdirSync(path.join(process.env.LOCALAPPDATA, 'ms-playwright'))
  .filter(item => /^chromium-\d+$/.test(item))
  .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))[0]
const executablePath = path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe')
const directory = 'docs/yxz-audit/visual-r70'
mkdirSync(directory, { recursive: true })
const browser = await chromium.launch({ executablePath })
const results = []
try {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto('http://127.0.0.1:5199/yxz-avatar', { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
    const canvas = page.locator('.yxz-real-model-canvas canvas')
    const box = await canvas.boundingBox()
    assert.ok(box?.width > 0 && box.height > 0)
    const initialClock = await page.evaluate(() => window.__yxzDebug.motionTime())
    const before = await canvas.screenshot()
    await page.waitForFunction(time => window.__yxzDebug.motionTime() >= time + 2, initialClock, { timeout: 120000 })
    const after = await canvas.screenshot()
    const beforePixels = await sharp(before).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
    const afterPixels = await sharp(after).ensureAlpha().raw().toBuffer()
    let colored = 0
    let changed = 0
    for (let i = 0; i < afterPixels.length; i += 4) {
      if (Math.max(afterPixels[i], afterPixels[i + 1], afterPixels[i + 2]) - Math.min(afterPixels[i], afterPixels[i + 1], afterPixels[i + 2]) > 40)
        colored++
      if (Math.abs(beforePixels.data[i] - afterPixels[i]) + Math.abs(beforePixels.data[i + 1] - afterPixels[i + 1]) + Math.abs(beforePixels.data[i + 2] - afterPixels[i + 2]) > 12)
        changed++
    }
    const finalClock = await page.evaluate(() => window.__yxzDebug.motionTime())
    const prefix = `${directory}/${viewport.width}`
    await page.screenshot({ path: `${prefix}-page.png` })
    writeFileSync(`${prefix}-canvas.png`, after)
    assert.ok(colored > 100, 'canvas must contain colored model pixels')
    assert.ok(changed > 50, 'model must visibly move')
    assert.deepEqual(errors, [])
    const row = { viewport, box, coloredPixels: colored, changedPixels: changed, modelSeconds: finalClock - initialClock, errors }
    results.push(row)
    console.log(row)

    // Read-only A/B diagnosis: the browser context is discarded afterwards.
    if (viewport.width === 1440) {
      await page.getByRole('button', { name: '暂停', exact: true }).click()
      await page.screenshot({ path: `${prefix}-paused.png` })
      row.rimMaterials = await page.evaluate(() => window.__yxzDebug.setUniform('parametricRimColorFactor', [0.06, 0.075, 0.10]))
      await page.screenshot({ path: `${prefix}-low-rim.png` })
      row.sidesChanged = await page.evaluate(() => window.__yxzDebug.setSide(window.__yxzDebug.three.FrontSide))
      await page.screenshot({ path: `${prefix}-front-side.png` })
      await page.evaluate(() => {
        const debug = window.__yxzDebug
        debug.setSide(debug.three.DoubleSide)
        debug.setUniform('parametricRimColorFactor', [0.52, 0.63, 0.84])
        window.__yxzVrm.scene.traverse(object => {
          if (!object.isMesh)
            return
          for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
            if (material.name.startsWith('tripo_')) {
              material.side = debug.three.FrontSide
              material.needsUpdate = true
            }
          }
        })
      })
      for (const angle of [-15, 0, 15]) {
        await page.evaluate(angle => { window.__yxzVrm.scene.rotation.y = angle * Math.PI / 180 }, angle)
        await page.screenshot({ path: `${prefix}-shell-front-${angle}.png` })
      }
    }
    await page.close()
  }
}
finally {
  await browser.close()
  writeFileSync(`${directory}/report.json`, JSON.stringify(results, null, 2))
}
