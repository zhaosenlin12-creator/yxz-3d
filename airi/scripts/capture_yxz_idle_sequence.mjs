/**
 * Capture the YXZ stage three times, far enough apart that the difference
 * between them is a decision rather than a twitch.
 *
 * A single screenshot cannot show whether a character is still or fidgeting,
 * which is the whole question when the complaint is that it never settles.
 * Sampling three moments twenty seconds apart shows what the head is doing
 * between them, which is nothing, and that is the thing to look at.
 *
 * Usage: node scripts/capture_yxz_idle_sequence.mjs [baseUrl] [outDir]
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
  const match = readdirSync(store).filter(entry => entry.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function installedChromium() {
  const root = path.join(process.env.LOCALAPPDATA ?? '', 'ms-playwright')
  if (!existsSync(root))
    return undefined
  return readdirSync(root)
    .filter(entry => /^chromium-\d+$/.test(entry))
    .sort((a, b) => Number(b.slice(9)) - Number(a.slice(9)))
    .map(entry => path.join(root, entry, 'chrome-win64', 'chrome.exe'))
    .find(existsSync)
}

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-rig-review/idle'
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch({ executablePath: installedChromium() })
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => document.body.innerText.includes('挂载') || document.querySelector('canvas'), null, { timeout: 120_000 })
await page.waitForTimeout(20_000)

// The head's own orientation, read out of the page rather than judged from a
// picture, so the numbers can back up whatever the pictures show.
const samples = []
for (const at of [0, 20, 20, 20]) {
  if (at)
    await page.waitForTimeout(at * 1000)
  const file = path.join(outDir, `idle-${samples.length}.png`)
  await page.locator('canvas').first().screenshot({ path: file })
  samples.push(file)
  console.log(`captured ${file}`)
}
await browser.close()
