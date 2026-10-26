/**
 * Drive the YXZ avatar QA page in a real browser and capture each state.
 *
 * Usage: node scripts/capture_yxz_avatar.mjs [baseUrl] [outDir]
 */

import { mkdir, writeFile } from 'node:fs/promises'
import { existsSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

/**
 * Playwright is a transitive dependency here, so pnpm keeps it out of the
 * root `node_modules`. Fall back to the virtual store before giving up.
 */
async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}

  const store = path.resolve('node_modules/.pnpm')
  if (!existsSync(store))
    throw new Error('playwright not found and no pnpm store present')
  const match = readdirSync(store)
    .filter(entry => entry.startsWith('playwright@'))
    .sort()
    .at(-1)
  if (!match)
    throw new Error('playwright is not installed')
  const entry = path.join(store, match, 'node_modules', 'playwright', 'index.js')
  if (!existsSync(entry))
    throw new Error(`playwright entry point missing at ${entry}`)
  return import(pathToFileURL(entry).href)
}

// playwright ships CommonJS, so the named exports can land on `default`
// depending on the interop path.
const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

if (!chromium) {
  throw new Error(`could not resolve playwright chromium (keys: ${Object.keys(playwright).join(', ')})`)
}

const baseUrl = process.argv[2] ?? 'http://localhost:5199'
const outDir = process.argv[3] ?? 'docs/yxz-rig-review/browser'
const pageUrl = `${baseUrl}/yxz-avatar`

const consoleLines = []

/**
 * A representative frame of every clip, so the captures show the gesture
 * instead of the first frame of a cross-fade.  The times are in seconds
 * into the clip.
 */
const POSES = {
  idle: ['YXZ_Idle', 0.7],
  listening: ['YXZ_Listening', 1.3],
  thinking: ['YXZ_Thinking', 1.7],
  speaking: ['YXZ_Speaking', 1.1],
  processing: ['YXZ_Thinking', 2.6],
  success: ['YXZ_Success', 1.9],
}

async function main() {
  await mkdir(outDir, { recursive: true })

  const browser = await chromium.launch({
    executablePath: resolveChromiumExecutable(),
    args: [
      '--use-gl=angle',
      '--use-angle=swiftshader',
      '--enable-unsafe-swiftshader',
      '--disable-lcd-text',
    ],
  })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  page.on('console', (message) => {
    const line = `[${message.type()}] ${message.text()}`
    consoleLines.push(line)
    console.log(line)
  })
  page.on('pageerror', error => consoleLines.push(`[pageerror] ${error.message}`))

  console.log(`opening ${pageUrl}`)
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 })

  if (process.env.YXZ_PROBE_ONLY) {
    await page.waitForTimeout(Number(process.env.YXZ_PROBE_WAIT ?? 25_000))
    await page.screenshot({ path: `${outDir}/probe.png`, fullPage: false })
    console.log('mount readout:', await page.locator('.readout').innerText().catch(() => '(no readout)'))
    console.log('body text head:', (await page.locator('body').innerText()).slice(0, 400))
    await browser.close()
    return
  }

  // The VRM is ~14MB, so wait for the component to report a real mount rather
  // than a fixed sleep.
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )
  console.log('mounted')

  const stage = page.locator('.yxz-avatar-stage')
  const states = ['idle', 'listening', 'thinking', 'speaking', 'processing', 'success']
  const labels = {
    idle: '待机',
    listening: '聆听',
    thinking: '思考',
    speaking: '说话',
    processing: '生成中',
    success: '完成',
  }

  for (const state of states) {
    // Step one state at a time from Node: Vue flushes the DOM on a microtask,
    // so clicking repeatedly inside a single evaluate() would wrap around
    // before the label ever updates.
    for (let step = 0; step < 8; step++) {
      const label = (await page.locator('.row .value').innerText()).trim()
      if (label === labels[state])
        break
      await page.getByRole('button', { name: '切换' }).click()
      await page.waitForTimeout(120)
    }
    if (state === 'speaking') {
      await page.getByRole('button', { name: '模拟说话' }).click()
    }
    console.log(`state=${state} label=${(await page.locator('.row .value').innerText()).trim()}`)
    // Park the clip on a representative frame.  Waiting for wall-clock time
    // is not reproducible: the headless renderer only manages a couple of
    // frames a second, and each one advances the mixer by at most 0.1s.
    const [clip, time] = POSES[state]
    await page.evaluate(
      ([clipName, at]) => {
        window.__yxzDebug?.freeze(true)
        window.__yxzDebug?.snap?.(clipName, at)
      },
      [clip, time],
    )
    // Give the renderer a frame to pick the new pose up.
    await page.waitForTimeout(2200)
    await stage.screenshot({ path: `${outDir}/state-${state}.png` })
    if (state === 'idle' || state === 'speaking') {
      // The eye construction is the part that is impossible to judge from a
      // full-body frame, so crop the head out of the canvas at native pixels.
      const box = await page.locator('.yxz-real-model-canvas canvas').boundingBox()
      if (box) {
        const width = Math.min(box.width * 0.46, 460)
        const height = Math.min(box.height * 0.42, 400)
        await page.screenshot({
          path: `${outDir}/head-${state}.png`,
          clip: {
            x: box.x + box.width / 2 - width / 2,
            y: box.y + box.height * 0.06,
            width,
            height,
          },
        })
      }
    }
    console.log(`captured ${state}`)
  }

  // Close-up on the face, where the eye/iris quality and the toon terminator
  // are judged.
  await page.evaluate(() => {
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  await page.waitForTimeout(2200)
  await page.locator('.yxz-real-model-canvas canvas').screenshot({ path: `${outDir}/canvas-closeup.png` })

  // Where the eyes are actually pointing, in degrees away from the rest
  // rotation.  A VRM that "looks at you" but barely moves its eyes is the
  // single most common way a model ends up reading as lifeless.
  const gaze = await page.evaluate(() => {
    const vrm = window.__yxzVrm
    if (!vrm?.humanoid)
      return null
    const measure = (name) => {
      const raw = vrm.humanoid.getRawBoneNode(name)
      const rest = vrm.humanoid.rawRestPose?.[name]
      if (!raw || !rest)
        return null
      const q = raw.quaternion
      const r = { x: rest.rotation[0], y: rest.rotation[1], z: rest.rotation[2], w: rest.rotation[3] }
      const dot = Math.min(1, Math.abs(q.x * r.x + q.y * r.y + q.z * r.z + q.w * r.w))
      return +(2 * Math.acos(dot) * 180 / Math.PI).toFixed(2)
    }
    return {
      yaw: +vrm.lookAt.yaw.toFixed(2),
      pitch: +vrm.lookAt.pitch.toFixed(2),
      leftEyeTurnDeg: measure('leftEye'),
      rightEyeTurnDeg: measure('rightEye'),
    }
  })
  console.log('gaze:', JSON.stringify(gaze))

  const readout = await page.locator('.readout').innerText()
  await writeFile(`${outDir}/console.log`, consoleLines.join('\n'), 'utf8')
  console.log('--- readout ---')
  console.log(readout)

  await browser.close()
}

/**
 * The bundled Playwright expects a Chromium build that is not present on this
 * machine, so fall back to whichever full Chromium revision *is* installed.
 */
function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH

  const root = path.join(
    process.env.LOCALAPPDATA ?? path.join(process.env.USERPROFILE ?? '', 'AppData', 'Local'),
    'ms-playwright',
  )
  if (!existsSync(root))
    return undefined

  const revisions = readdirSync(root)
    .filter(entry => entry.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))

  for (const revision of revisions) {
    const executable = path.join(root, revision, 'chrome-win64', 'chrome.exe')
    if (existsSync(executable))
      return executable
  }
  return undefined
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

