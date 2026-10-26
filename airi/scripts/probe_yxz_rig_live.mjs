/**
 * Dump the live YXZ rig state from the browser.
 *
 * Two things are impossible to judge from a screenshot: whether the body
 * motion is actually reaching the bones, and where the eyes are really
 * pointing.  This prints the numbers for both.
 */

import process from 'node:process'
import { existsSync, readdirSync } from 'node:fs'
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
  if (!existsSync(root))
    return undefined
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
page.on('console', (message) => {
  const text = message.text()
  if (/VRM|Expression|humanoid|lookAt/i.test(text))
    console.log(`[console] ${text}`)
})
await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)
await page.waitForTimeout(2500)

const report = await page.evaluate(() => {
  const vrm = window.__yxzVrm
  if (!vrm)
    return { error: 'no __yxzVrm handle' }
  const debug = window.__yxzDebug ?? {}

  const round = (n) => +n.toFixed(4)
  const bones = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
    'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
    'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
    'leftEye', 'rightEye']

  const out = {}
  for (const name of bones) {
    const raw = vrm.humanoid?.getRawBoneNode(name)
    const norm = vrm.humanoid?.getNormalizedBoneNode(name)
    if (!raw)
      continue
    const world = raw.getWorldPosition(raw.position.clone())
    const rest = vrm.humanoid.rawRestPose?.[name]
    out[name] = {
      rawLocal: raw.quaternion.toArray().map(round),
      rawWorld: raw.getWorldQuaternion(raw.quaternion.clone()).toArray().map(round),
      normLocal: norm ? norm.quaternion.toArray().map(round) : null,
      restLocal: rest ? rest.rotation.map(round) : null,
      world: [world.x, world.y, world.z].map(round),
    }
  }

  const lookAt = vrm.lookAt
  const target = lookAt?.target

  return {
    clip: debug.clip?.() ?? null,
    clipTime: debug.clipTime?.() ?? null,
    frames: debug.frames?.() ?? null,
    mixerTime: debug.mixerTime?.() ?? null,
    weight: debug.weight?.() ?? null,
    playing: debug.playing?.() ?? null,
    actionCount: debug.actionCount?.() ?? null,
    autoUpdateHumanBones: vrm.humanoid?.autoUpdateHumanBones,
    lookAt: lookAt
      ? {
          yaw: round(lookAt.yaw),
          pitch: round(lookAt.pitch),
          faceFront: lookAt.faceFront.toArray().map(round),
          offsetFromHeadBone: lookAt.offsetFromHeadBone.toArray().map(round),
          target: target ? [target.position.x, target.position.y, target.position.z].map(round) : null,
          type: lookAt.type,
        }
      : null,
    bones: out,
  }
})

console.log(JSON.stringify(report, null, 2))
await browser.close()
