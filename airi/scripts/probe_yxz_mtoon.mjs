/**
 * Print the MToon material as the running page sees it.
 *
 * A material change that is written against the wrong property name is a
 * change that is silently not made: the scene still loads, still renders,
 * and looks exactly as it did before.  This dumps the material's own keys
 * and the values of every MToon factor on it, so the name to write to is
 * read off the object rather than remembered.
 *
 * Usage: node scripts/probe_yxz_mtoon.mjs [baseUrl]
 */

import { existsSync, readdirSync } from 'node:fs'
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

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 800, height: 600 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(() => {
  const out = []
  window.__yxzVrm.scene.traverse((object) => {
    if (!object.isMesh)
      return
    const list = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of list) {
      if (!material || !material.name.startsWith('tripo_'))
        continue
      const uniforms = material.uniforms ?? {}
      const row = { mesh: object.name, material: material.name, type: material.type }
      for (const [key, value] of Object.entries(uniforms)) {
        if (value?.value?.isColor)
          row[key] = `#${value.value.getHexString()}`
        else if (typeof value?.value === 'number')
          row[key] = value.value
        else
          row[key] = String(value?.value)
      }
      row.ownKeys = Object.keys(material).filter(key => !key.startsWith('_')).join(',')
      out.push(row)
    }
  })
  return out
})

console.log(JSON.stringify(report, null, 2))
await browser.close()
