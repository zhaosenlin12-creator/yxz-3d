/**
 * Sample the live YXZ rig from the browser and report what each bone is
 * doing, in degrees, second by second.
 *
 * The offline probe models the living layer; this one watches the page
 * itself.  Anything the offline model gets wrong -- a bone it thinks is
 * still that the page is actually spinning, a clip that was supposed to be
 * calmed and is not -- shows up here and nowhere else.
 *
 * Usage:
 *   node scripts/probe_yxz_live_bones.mjs [baseUrl] [--seconds 30] [--rate 10]
 */

import { existsSync, readdirSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

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

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  if (!existsSync(root))
    return undefined
  const revision = readdirSync(root)
    .filter(entry => /^chromium-\d+$/.test(entry))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const args = process.argv.slice(2)
function flag(name, fallback) {
  const at = args.indexOf(`--${name}`)
  return at < 0 ? fallback : Number(args[at + 1])
}
const positional = args.filter((token, index) =>
  !token.startsWith('--') && !(index > 0 && args[index - 1].startsWith('--')))
const baseUrl = positional[0] ?? 'http://127.0.0.1:5199'
const seconds = flag('seconds', 30)
const rate = flag('rate', 10)
// The headless browser draws at about a frame a second, so a run at the
// character's own clock would only see a second or two of it.  The page
// has a hook for running the character's clock faster than the wall
// clock, and this uses it, so a thirty second run covers thirty seconds
// of the character's own time.
const timeScale = flag('timeScale', 1)
const bones = (flag('bones', 'head,neck,upperChest,chest,spine,hips,halo') ? String(flag('bones', 'head,neck,upperChest,chest,spine,hips,halo')) : '').split(',')

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => Boolean(window.__yxzVrm), undefined, { timeout: 60000 })
if (timeScale !== 1)
  await page.evaluate(scale => window.__yxzDebug?.timeScale?.(scale), timeScale)

const samples = await page.evaluate(async ({ seconds, rate, bones }) => {
  // The rig the page actually drives, taken from the component's own debug
  // hook rather than by name: three-vrm keeps a second, normalised rig
  // whose nodes carry the same names, and a name lookup finds that one
  // instead of the skeleton the character is actually posed on.
  const life = window.__yxzDebug.life()
  const wanted = new Set(bones)
  const out = []
  const start = performance.now()
  const step = 1000 / rate
  let next = start
  while (performance.now() - start < seconds * 1000) {
    await new Promise(resolve => setTimeout(resolve, Math.max(0, next - performance.now())))
    next += step
    const row = { t: +((performance.now() - start) / 1000).toFixed(2), bones: {} }
    for (const entry of life) {
      if (!wanted.has(entry.bone))
        continue
      // World = parent world * local.  The component hands back both
      // halves, so the bone can be read the way the camera sees it.
      const p = entry.parentWorld
      const l = entry.local
      if (p.length < 4 || l.length < 4) {
        row.bones[entry.bone] = null
        continue
      }
      const e = {
        x: p[3] * l[0] + p[0] * l[3] + p[1] * l[2] - p[2] * l[1],
        y: p[3] * l[1] - p[0] * l[2] + p[1] * l[3] + p[2] * l[0],
        z: p[3] * l[2] + p[0] * l[1] - p[1] * l[0] + p[2] * l[3],
        w: p[3] * l[3] - p[0] * l[0] - p[1] * l[1] - p[2] * l[2],
      }
      // The same XYZ triple three itself would read out of the quaternion.
      const m8 = 2 * (e.x * e.z + e.w * e.y)
      const m9 = 2 * (e.y * e.z - e.w * e.x)
      const m10 = 1 - 2 * (e.x * e.x + e.y * e.y)
      const m4 = 2 * (e.x * e.y + e.w * e.z)
      const m5 = 1 - 2 * (e.x * e.x + e.z * e.z)
      row.bones[entry.bone] = [
        +(Math.asin(Math.max(-1, Math.min(1, m8))) * 180 / Math.PI).toFixed(2),
        +(Math.atan2(-m9, m10) * 180 / Math.PI).toFixed(2),
        +(Math.atan2(-m4, m5) * 180 / Math.PI).toFixed(2),
      ]
    }
    out.push(row)
  }
  return out
}, { seconds, rate, bones })

for (const name of bones) {
  const values = samples.map(row => row.bones[name]).filter(Boolean)
  if (values.length === 0) {
    console.log(`${name.padEnd(12)} (not found)`)
    continue
  }
  const axis = [0, 1, 2].map(a => {
    const series = values.map(v => v[a])
    const mean = series.reduce((s, v) => s + v, 0) / series.length
    const sd = Math.sqrt(series.reduce((s, v) => s + (v - mean) ** 2, 0) / series.length)
    return { mean: mean.toFixed(2), sd: sd.toFixed(2), min: Math.min(...series).toFixed(2), max: Math.max(...series).toFixed(2) }
  })
  // How much of the run the bone sat within a third of a degree of where it
  // was half a second earlier.
  const window = Math.round(rate * 0.5)
  let held = 0
  for (let i = window; i < values.length; i++) {
    const dx = values[i][0] - values[i - window][0]
    const dy = values[i][1] - values[i - window][1]
    const dz = values[i][2] - values[i - window][2]
    if (Math.hypot(dx, dy, dz) < 0.3)
      held++
  }
  console.log(
    `${name.padEnd(12)} pitch ${axis[0].min}..${axis[0].max} (sd ${axis[0].sd})`
    + `   yaw ${axis[1].min}..${axis[1].max} (sd ${axis[1].sd})`
    + `   roll ${axis[2].min}..${axis[2].max} (sd ${axis[2].sd})`
    + `   held ${Math.round((held / Math.max(1, values.length - window)) * 100)}%`,
  )
}

console.log('\nsamples (t, head pitch/yaw/roll):')
for (const row of samples) {
  const head = row.bones.head
  console.log(`  ${String(row.t).padStart(6)}  ${head ? head.map(v => String(v).padStart(7)).join(' ') : '(none)'}`)
}

await browser.close()
