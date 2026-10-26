/**
 * Draw the YXZ idle motion as an image, because a table of numbers cannot
 * answer the only question that matters here: does it read as a person
 * standing, or as a thing oscillating.  Rocking is visible in the shape of
 * the trace long before it is visible in a mean or a percentile.
 *
 * The traces come from `probe_yxz_motion.mjs --dump`, which runs the real
 * mixer and the real living layer offline at 60Hz.
 *
 * Usage:
 *   node scripts/plot_yxz_motion.mjs <series.json> <out.png> [--bone head]
 */

import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'
import { existsSync, readdirSync } from 'node:fs'

/**
 * The pnpm store can hold a Playwright whose pinned browser revision is not
 * the one installed here, so the newest Chromium on disk is named explicitly
 * rather than letting the launcher go looking for a directory that is absent.
 */
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

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
  const match = readdirSync(store).filter(entry => entry.startsWith('playwright@')).sort().at(-1)
  if (!match)
    throw new Error('playwright is not installed')
  const entry = path.join(store, match, 'node_modules', 'playwright', 'index.js')
  return import(pathToFileURL(entry).href)
}

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

const seriesFile = process.argv[2]
const outFile = process.argv[3] ?? 'docs/yxz-audit/motion.png'
const boneArg = process.argv.indexOf('--bone')
const data = JSON.parse(readFileSync(seriesFile, 'utf8'))
const bone = boneArg > 0 ? process.argv[boneArg + 1] : 'head'
const series = data.bones[bone]
if (!series)
  throw new Error(`no series for ${bone}; have ${Object.keys(data.bones).join(', ')}`)

const W = 1600
const PAD = 56
const ROW = 132
const H = PAD * 2 + ROW * 4
const plotW = W - PAD * 2
const rate = data.rate ?? 10
const count = series.x.length

const AXES = [
  { key: 'x', label: 'pitch', color: '#c2410c' },
  { key: 'y', label: 'yaw', color: '#0e7490' },
  { key: 'z', label: 'roll', color: '#4d7c0f' },
]
let limit = 1
for (const axis of AXES) {
  for (const v of series[axis.key])
    limit = Math.max(limit, Math.abs(v))
}
limit = Math.ceil(limit / 5) * 5

function polyline(values, top, height) {
  const step = plotW / Math.max(1, values.length - 1)
  return values
    .map((v, i) => `${(PAD + i * step).toFixed(1)},${(top + height / 2 - (v / limit) * (height / 2 - 6)).toFixed(1)}`)
    .join(' ')
}

const rows = AXES.map((axis, index) => {
  const top = PAD + index * ROW
  return `
    <text x="${PAD - 8}" y="${top + 18}" class="axis">${axis.label}</text>
    <rect x="${PAD}" y="${top}" width="${plotW}" height="${ROW}" fill="#0f141a" stroke="#22303d" />
    <line x1="${PAD}" y1="${top + ROW / 2}" x2="${PAD + plotW}" y2="${top + ROW / 2}" stroke="#31465a" stroke-dasharray="3 5" />
    <polyline points="${polyline(series[axis.key], top, ROW)}" fill="none" stroke="${axis.color}" stroke-width="1.4" />
    <text x="${PAD + plotW + 8}" y="${top + 18}" class="axis">±${limit}°</text>
  `
}).join('')

// A minute grid, because the question "is this on a beat" is only answerable
// against the clock.
const grid = Array.from({ length: Math.floor(data.seconds / 30) + 1 }, (_, i) => {
  const x = PAD + (i * 30 * rate / count) * plotW
  return `<line x1="${x}" y1="${PAD}" x2="${x}" y2="${PAD + ROW * 3}" stroke="#1b2733" />
    <text x="${x}" y="${PAD + ROW * 3 + 16}" class="tick">${i * 30}s</text>`
}).join('')

// Dwell shading: runs where the pose stayed within a degree of where it was
// half a second earlier.  These are the still stretches, and whether they are
// long enough to read as standing still is the whole question.
const holds = []
let run = null
const window = Math.round(rate * 0.5)
const angles = series.step
for (let i = 0; i < count; i++) {
  const still = i < window ? false : angles[i - window] < 0.4
  if (still && !run)
    run = [i, i]
  else if (still)
    run[1] = i
  else if (run) {
    holds.push(run)
    run = null
  }
}
if (run)
  holds.push(run)
const px = plotW / count
const shading = holds
  .filter(([a, b]) => b - a > rate * 1.5)
  .map(([a, b]) => `<rect x="${PAD + a * px}" y="${PAD}" width="${(b - a) * px}" height="${ROW * 3}" fill="#22c55e" opacity="0.09" />`)
  .join('')
const legend = `<text x="${PAD}" y="${PAD - 14}" class="title">${path.basename(seriesFile)}  ·  ${bone}  ·  ${data.status}  ·  ${data.seconds}s</text>`
const legendNote = `<text x="${W - PAD}" y="${PAD - 14}" class="axis" text-anchor="end">shaded = pose held within 0.4° over 0.5s</text>`

const html = `<!doctype html><meta charset="utf-8"><style>
  body{margin:0;background:#0b0f14;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  svg{display:block}
  .axis{fill:#7d93a8;font-size:13px}
  .tick{fill:#5d7186;font-size:12px;text-anchor:middle}
  .title{fill:#d6e4f0;font-size:15px}
</style>
<svg width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg">${legend}${legendNote}${shading}${grid}${rows}</svg>`

const browser = await chromium.launch({ executablePath: installedChromium() })
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })
await page.setContent(html)
await page.locator('svg').screenshot({ path: outFile })
await browser.close()
console.log(`${outFile}  ${W}x${H}  ${bone}  ${count} samples`)
