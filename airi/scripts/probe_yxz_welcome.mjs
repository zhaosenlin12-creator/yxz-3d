/**
 * Check that the welcome flow still works end to end.
 *
 * Two things are checked separately on purpose:
 *
 *   the proactive question   the intro line is injected as a chat message,
 *                            so it has to be in the message list and on
 *                            screen
 *   the spoken welcome       the voice goes through `speechSynthesis`, which
 *                            Chrome will not start without a user gesture,
 *                            so the page has to offer a way to start it
 *
 * Usage: node scripts/probe_yxz_welcome.mjs [baseUrl]
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
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })

const errors = []
page.on('pageerror', error => errors.push(error.message))

await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForTimeout(40_000)

const state = await page.evaluate(async () => {
  const body = document.body.innerText
  const button = [...document.querySelectorAll('button')]
    .find(element => element.textContent?.includes('🔊'))
  const voices = window.speechSynthesis?.getVoices?.() ?? []
  return {
    introInPage: body.includes('我是宜小智，你的 AI 智能创造伙伴'),
    introBubble: [...document.querySelectorAll('*')]
      .some(element => element.children.length === 0 && element.textContent?.includes('我是宜小智')),
    replayButton: button ? button.textContent.trim() : null,
    replayDisabled: button ? button.disabled : null,
    voiceCount: voices.length,
    chineseVoices: voices.filter(v => v.lang?.toLowerCase().startsWith('zh')).map(v => v.name),
  }
})

console.log('STATE', JSON.stringify(state, null, 2))

// Start the speech the way a user would, with a real click, and see whether
// the browser accepts it.
const button = page.locator('button', { hasText: '🔊' }).first()
if (await button.count()) {
  await button.click()
  await page.waitForTimeout(4000)
  const after = await page.evaluate(() => {
    const element = [...document.querySelectorAll('button')].find(item => item.textContent?.includes('🔊'))
    return { label: element?.textContent?.trim() ?? null, speaking: window.speechSynthesis?.speaking ?? null }
  })
  console.log('AFTER_CLICK', JSON.stringify(after))
}
else {
  console.log('AFTER_CLICK no replay button found')
}

console.log('PAGE_ERRORS', JSON.stringify(errors))
await browser.close()
