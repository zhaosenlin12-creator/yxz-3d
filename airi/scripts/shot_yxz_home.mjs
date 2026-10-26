/** The real entry point, and the two things that were reported missing
 * from it: the proactive greeting and the voice that reads it.
 *
 * Usage: node scripts/shot_yxz_home.mjs [baseUrl] [out.png]
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
  const exe = path.join(root, revision, 'chrome-win64', 'chrome.exe')
  return existsSync(exe) ? exe : undefined
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const out = process.argv[3] ?? 'docs/yxz-audit/home.png'
const width = Number(process.argv[4] ?? 1440)
const height = Number(process.argv[5] ?? 900)
// A query on the page, so the same picture can be taken with a part of
// the render stack switched off.
const query = process.argv[6] ?? ''

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width, height } })
const errors = []
const logs = []
page.on('pageerror', error => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error')
    errors.push(`console: ${message.text()}`)
  else if (/Stage|TTS|speech|YXZ|宜小智/i.test(message.text()))
    logs.push(message.text())
})

await page.goto(`${baseUrl}/${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForTimeout(12_000)

const text = await page.evaluate(() => document.body.innerText)
const report = {
  url: page.url(),
  hasProactiveGreeting: text.includes('我是宜小智'),
  greetingSnippet: text.includes('我是宜小智')
    ? text.slice(Math.max(0, text.indexOf('我是宜小智') - 40), text.indexOf('我是宜小智') + 120)
    : null,
  hasSpeakButton: /点击.*播放|点击.*说话|播放语音|开启语音/.test(text),
  speechSynthesisAvailable: await page.evaluate(() => typeof window.speechSynthesis !== 'undefined'),
  voices: await page.evaluate(() => {
    if (typeof window.speechSynthesis === 'undefined')
      return []
    return window.speechSynthesis.getVoices().map(v => `${v.name} (${v.lang})`).slice(0, 8)
  }),
  logs: logs.slice(0, 20),
  errors: errors.slice(0, 20),
}
console.log(JSON.stringify(report, null, 2))
await page.screenshot({ path: out })
console.log(`HOME ${out}`)
await browser.close()
