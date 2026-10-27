/**
 * Per-bone motion report for the running YXZ avatar.
 *
 * "The figure moves" is not a measurement.  What matters is *which* bones
 * move, because a bone that shares its geometry with its neighbours
 * tears the mesh when it turns, and a bone that owns its geometry
 * rigidly does not.  This samples every bone's local and world rotation
 * over a stretch of the character's own time and reports the range each
 * one covers.
 *
 * The character's clock is run faster than the wall clock, because the
 * software renderer manages about one frame a second and a slow
 * character's time would otherwise be sampled too coarsely to see
 * anything.
 *
 * Usage:
 *   node scripts/probe_yxz_bone_motion.mjs [baseUrl] [seconds] [timeScale]
 */

import path from 'node:path'
import process from 'node:process'

import { readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
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

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const seconds = Number(process.argv[3] ?? 40)
const timeScale = Number(process.argv[4] ?? 6)

const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 900, height: 700 } })
const pageErrors = []
page.on('pageerror', error => pageErrors.push(error.message))

await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
await page.waitForFunction(
  () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
  null,
  { timeout: 180_000 },
)

const report = await page.evaluate(async ({ seconds, timeScale }) => {
  const vrm = window.__yxzVrm
  const debug = window.__yxzDebug
  if (!vrm || !debug)
    return { error: 'no handle' }

  const nodes = []
  vrm.scene.traverse((object) => {
    if (object.isBone)
      nodes.push(object)
  })

  const quat = () => new vrm.scene.quaternion.constructor()
  const vec = () => new vrm.scene.position.constructor()

  const angleBetween = (a, b) => {
    const dot = Math.abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w)
    return 2 * Math.acos(Math.min(1, Math.max(-1, dot))) * 180 / Math.PI
  }

  const stats = new Map()
  for (const node of nodes) {
    stats.set(node.name, {
      name: node.name,
      localFirst: node.quaternion.clone(),
      worldFirst: node.getWorldQuaternion(quat()),
      posFirst: node.getWorldPosition(vec()),
      localRange: 0,
      worldRange: 0,
      posRange: 0,
      samples: 0,
    })
  }

  debug.timeScale(timeScale)
  // Warm up before the reference pose is taken.
  //
  // The clip fades in over four tenths of a second of the character's
  // time, and the first sample lands in the middle of that fade, when
  // the bones are still on their rest pose.  Every bone then reads its
  // own arrival at the held pose as movement, which is exactly the
  // measurement this report is supposed to be free of.
  await new Promise(resolve => setTimeout(resolve, 12_000))
  for (const node of nodes) {
    const entry = stats.get(node.name)
    entry.localFirst = node.quaternion.clone()
    entry.worldFirst = node.getWorldQuaternion(quat())
    entry.posFirst = node.getWorldPosition(vec())
  }
  const started = performance.now()
  // The head, sampled on its own axes.
  //
  // "The head moves" is not the question.  The question is whether it
  // moves in a *shape*: a head that tips while it turns, and turns
  // again while it is still tipped, draws a closed curve, and a closed
  // curve is the circling.  So the head's own pitch, yaw and roll are
  // recorded separately, and a yaw that stays near zero while the pitch
  // and the roll move is a head that drifts rather than a head that
  // circles.
  const headAxes = { pitch: [], yaw: [], roll: [] }
  const headNode = nodes.find(node => node.name === 'head')
  const euler = new vrm.scene.rotation.constructor()
  while (performance.now() - started < seconds * 1000) {
    await new Promise(resolve => setTimeout(resolve, 120))
    if (headNode) {
      euler.setFromQuaternion(headNode.quaternion, 'YXZ')
      headAxes.pitch.push(euler.x * 180 / Math.PI)
      headAxes.yaw.push(euler.y * 180 / Math.PI)
      headAxes.roll.push(euler.z * 180 / Math.PI)
    }
    for (const node of nodes) {
      const entry = stats.get(node.name)
      const world = node.getWorldQuaternion(quat())
      const position = node.getWorldPosition(vec())
      entry.localRange = Math.max(entry.localRange, angleBetween(entry.localFirst, node.quaternion))
      entry.worldRange = Math.max(entry.worldRange, angleBetween(entry.worldFirst, world))
      entry.posRange = Math.max(entry.posRange, entry.posFirst.distanceTo(position))
      entry.samples++
    }
  }
  debug.timeScale(1)

  const rows = Array.from(stats.values(), entry => ({
    bone: entry.name,
    localDeg: +entry.localRange.toFixed(2),
    worldDeg: +entry.worldRange.toFixed(2),
    worldMove: +entry.posRange.toFixed(4),
    samples: entry.samples,
  }))
    .filter(row => row.localDeg > 0.05 || row.worldMove > 0.002)
    .sort((a, b) => b.localDeg - a.localDeg)

  const axisRange = values => values.length
    ? +Math.max(...values.map((value, index) => Math.abs(value - values[0]))).toFixed(2)
    : 0

  return {
    characterTime: +(debug.motionTime?.() ?? 0).toFixed(1),
    headAxes: {
      pitchRange: axisRange(headAxes.pitch),
      yawRange: axisRange(headAxes.yaw),
      rollRange: axisRange(headAxes.roll),
      samples: headAxes.pitch.length,
    },
    moving: rows,
    still: rows.filter(row => row.localDeg < 0.05).map(row => row.bone),
    totalBones: nodes.length,
  }
}, { seconds, timeScale })

console.log(JSON.stringify(report, null, 2))
if (pageErrors.length)
  console.log('pageErrors', pageErrors)
await browser.close()
