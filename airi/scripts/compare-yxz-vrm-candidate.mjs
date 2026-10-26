import path from 'node:path'
import process from 'node:process'

import { mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const store = path.resolve('node_modules/.pnpm')
const playwrightEntry = readdirSync(store).find(name => name.startsWith('playwright@'))
const { chromium } = require(path.join(store, playwrightEntry, 'node_modules/playwright'))
const revision = readdirSync(path.join(process.env.LOCALAPPDATA, 'ms-playwright'))
  .filter(name => name.startsWith('chromium-'))
  .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))[0]
const executablePath = path.join(process.env.LOCALAPPDATA, 'ms-playwright', revision, 'chrome-win64/chrome.exe')

const candidate = path.resolve(process.argv[2])
const outDir = path.resolve(process.argv[3] ?? 'docs/yxz-audit/candidates/compare')
mkdirSync(outDir, { recursive: true })
const browser = await chromium.launch({ executablePath })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error')
    console.info('BROWSER_CONSOLE_ERROR', message.text())
})
await page.route('**/*', async (route) => {
  const url = new URL(route.request().url())
  if (
    !url.pathname.endsWith('/yxz.vrm')
    || !['fetch', 'xhr'].includes(route.request().resourceType())
  ) {
    await route.continue()
    return
  }
  console.info('YXZ_CANDIDATE_ROUTE', url.href)
  await route.fulfill({
    status: 200,
    contentType: 'model/gltf-binary',
    body: readFileSync(candidate),
  })
})
await page.goto('http://127.0.0.1:5199/yxz-avatar', { waitUntil: 'domcontentloaded' })
try {
  await page.waitForFunction(() => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted', null, { timeout: 120000 })
}
catch {
  console.info('YXZ_CANDIDATE_STATE', await page.locator('.readout').textContent().catch(() => 'missing'))
  console.info('YXZ_CANDIDATE_ERRORS', errors)
  throw new Error('candidate did not mount')
}
await page.waitForTimeout(1200)
await page.screenshot({ path: path.join(outDir, 'candidate-page.png') })
const canvas = page.locator('.yxz-real-model-canvas canvas')
await canvas.screenshot({ path: path.join(outDir, 'candidate-canvas.png') })

await page.getByRole('button', { name: '暂停', exact: true }).click()
await page.evaluate(() => {
  const canvas = document.querySelector('.yxz-real-model-canvas canvas')
  for (const element of document.querySelectorAll('body *')) {
    if (element === canvas || element.contains(canvas))
      continue
    element.style.setProperty('display', 'none', 'important')
  }
  window.__yxzDebug?.freeze(true)
  window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
})
await page.waitForTimeout(900)

const shots = [
  { name: 'head', eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  { name: 'crown', eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  { name: 'face-oblique', eye: [1.05, 2.55, 2.9], look: [0, 2.45, 0.45] },
  { name: 'body', eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
]
for (const shot of shots) {
  await page.evaluate(([eye, look]) => {
    const camera = window.__yxzDebug?.camera?.()
    if (!camera)
      throw new Error('YXZ camera debug hook is unavailable')
    camera.position.set(eye[0], eye[1], eye[2])
    camera.lookAt(look[0], look[1], look[2])
    camera.updateProjectionMatrix()
  }, [shot.eye, shot.look])
  await page.waitForTimeout(500)
  await canvas.screenshot({ path: path.join(outDir, `${shot.name}.png`) })
}

console.info('YXZ_CANDIDATE_ERRORS', errors)
console.info('YXZ_CANDIDATE_CAPTURED', outDir)
await browser.close()
