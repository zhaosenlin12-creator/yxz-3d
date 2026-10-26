/**
 * Objective runtime verification of the YXZ avatar in a real browser.
 *
 * Screenshots alone cannot tell a playing clip from a frozen pose, so this
 * measures the rig directly: which clip each status selects, how far the
 * bones actually travel during it, and whether the face systems (blink,
 * gaze, visemes, expressions) produce non-zero values over time.
 *
 * Usage: node scripts/verify_yxz_runtime.mjs [baseUrl]
 */

import process from 'node:process'
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

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

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium

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

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error' && /YXZ|宜小智|three|VRM/i.test(message.text()))
    pageErrors.push(message.text())
})

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const frameProbe = await page.evaluate(() => new Promise((resolve) => {
  let frames = 0
  const started = performance.now()
  const tick = () => {
    frames++
    if (performance.now() - started < 1000)
      requestAnimationFrame(tick)
    else
      resolve({ frames, hidden: document.hidden, visibility: document.visibilityState })
  }
  requestAnimationFrame(tick)
}))
console.log('frame probe:', JSON.stringify(frameProbe))

const report = await page.evaluate(async () => {
  const vrm = window.__yxzVrm
  if (!vrm)
    return { error: 'no __yxzVrm handle' }
  const debug = window.__yxzDebug

  // Measure the real skeleton, not the humanoid proxy nodes: the proxies
  // three-vrm exposes via `getNormalizedBoneNode` are rest-pose helpers and do
  // not follow the animated bones.
  const nodes = []
  vrm.scene.traverse((object) => {
    if (object.isBone)
      nodes.push({ name: object.name, node: object })
  })

  const snapshot = () => nodes.map(({ node }) => {
    const p = node.getWorldPosition(new node.position.constructor())
    const q = node.getWorldQuaternion(new node.quaternion.constructor())
    return [p.x, p.y, p.z, q.x, q.y, q.z, q.w]
  })

  const expressionValues = () => {
    const out = {}
    for (const name of ['blink', 'blinkLeft', 'blinkRight', 'happy', 'angry', 'sad',
      'relaxed', 'surprised', 'aa', 'ih', 'ou', 'ee']) {
      out[name] = Number((vrm.expressionManager?.getValue(name) ?? 0).toFixed(4))
    }
    return out
  }

  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms))

  // Reach into the component's mixer through the clip it created on the VRM
  // scene. The mixer is not exposed, so drive the measurement off the pose
  // instead: if bones move, a clip is playing.
  const statuses = ['idle', 'listening', 'thinking', 'speaking', 'success']
  const results = {}

  for (const status of statuses) {
    // Drive the harness UI.
    const labels = { idle: '待机', listening: '聆听', thinking: '思考', speaking: '说话', success: '完成' }
    for (let i = 0; i < 8; i++) {
      const label = document.querySelector('.row .value')?.textContent?.trim()
      if (label === labels[status])
        break
      ;[...document.querySelectorAll('.row button')]
        .find(button => button.textContent.trim() === '切换')?.click()
      await wait(150)
    }

    let maxTranslation = 0
    let maxRotation = 0
    const expressionPeaks = {}
    const reference = snapshot()

    for (let frame = 0; frame < 90; frame++) {
      await wait(50)
      const now = snapshot()
      for (let i = 0; i < now.length; i++) {
        const dx = now[i][0] - reference[i][0]
        const dy = now[i][1] - reference[i][1]
        const dz = now[i][2] - reference[i][2]
        maxTranslation = Math.max(maxTranslation, Math.hypot(dx, dy, dz))
        const dot = Math.abs(now[i][3] * reference[i][3] + now[i][4] * reference[i][4]
          + now[i][5] * reference[i][5] + now[i][6] * reference[i][6])
        maxRotation = Math.max(maxRotation, 2 * Math.acos(Math.min(1, dot)))
      }
      const values = expressionValues()
      for (const [name, value] of Object.entries(values)) {
        expressionPeaks[name] = Math.max(expressionPeaks[name] ?? 0, value)
      }
    }

    results[status] = {
      maxBoneTranslation: +maxTranslation.toFixed(5),
      maxBoneRotationDeg: +(maxRotation * 180 / Math.PI).toFixed(2),
      expressionPeaks,
    }
  }

  // Gaze: the look-at target sits at the camera, so both eye bones should sit
  // at a non-identity world rotation and change as saccades fire.
  const eyeNodes = ['leftEye', 'rightEye']
    .map(name => nodes.find(entry => entry.name === name)?.node)
    .filter(Boolean)
  const gazeSamples = []
  for (let i = 0; i < 24; i++) {
    await wait(120)
    gazeSamples.push(eyeNodes.map((node) => {
      const q = node.getWorldQuaternion(new node.quaternion.constructor())
      return +q.y.toFixed(4)
    }))
  }
  const gazeSpread = Math.max(...gazeSamples.flat()) - Math.min(...gazeSamples.flat())

  return {
    boneCount: nodes.length,
    statuses: results,
    gazeYawSpread: +gazeSpread.toFixed(4),
    mixer: debug
      ? {
          actionCount: debug.actionCount(),
          mixerTime: debug.mixerTime(),
          clip: debug.clip(),
          clipTime: debug.clipTime(),
          playing: debug.playing(),
          weight: debug.weight(),
          frames: debug.frames(),
        }
      : null,
  }
})

await page.waitForTimeout(500)
console.log(JSON.stringify({ ...report, pageErrors }, null, 2))
await browser.close()
