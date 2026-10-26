/**
 * Tune the walk against the reference.
 *
 * The numbers that decide whether the figure reads as alive are a
 * handful of constants, and the relationship between them is not
 * something that can be reasoned out -- the size of the movement and
 * the speed of it pull against each other, and the pull towards the
 * middle fights the pull towards the edges.  So they are swept.
 *
 * Each candidate is written into a copy of the component, the copy is
 * measured by the same probe the last round was measured by, and the
 * result is scored against the reference on the axes that matter.
 *
 * Usage:
 *   node scripts/sweep_yxz_motion.mjs [--seconds 120] [--keep]
 */

import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'

const args = process.argv.slice(2)
const seconds = Number(args[args.indexOf('--seconds') + 1] ?? 120)
const keep = args.includes('--keep')
const root = path.resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const scene = path.join(root, 'packages/stage-ui-three/src/components/YXZRealModelScene.vue')
const vrm = path.join(root, 'packages/stage-ui-three/src/assets/vrm/models/yxz.vrm')
const source = readFileSync(scene, 'utf8')

// What the reference measures, and what it is worth to be near it.
const TARGET = {
  sdPitch: 2.62,
  sdRoll: 3.61,
  sdYaw: 0.41,
  ellipse: 0.976,
  yawEllipse: 0.594,
  path: 3.48,
  period: 10.4,
  episodes: 20.5,
  held: 8,
  episodeDur: 1.3,
  episodePeak: 4.63,
  snap: 8.25,
}

function setConst(text, name, value) {
  const pattern = new RegExp(`(const ${name}(?::[^=\\n]+)?\\s*=\\s*)([^\\n]*)`)
  if (!pattern.test(text))
    throw new Error(`${name} not found`)
  return text.replace(pattern, `$1${value}`)
}

function parseCompare(output) {
  const rows = {}
  for (const line of output.split('\n')) {
    const match = line.trim().match(/^(.*?)\s{2,}(\S.*)$/)
    if (!match)
      continue
    const label = match[1].trim()
    // The columns are the reference and the model.  A cell may itself
    // hold several numbers, written `a / b / c`.
    const cells = match[2].trim().split(/\s{2,}/)
    if (cells.length >= 2)
      rows[label] = cells.map(cell => (cell.includes('/')
        ? cell.split('/').map(v => Number(v.trim()))
        : Number(cell)))
  }
  return rows
}

function score(metrics) {
  // Column zero is the reference; column one is the model.
  const get = (label, column) => {
    const cell = metrics[label]?.[1]
    if (Array.isArray(cell))
      return cell[column]
    return column === 0 ? cell : undefined
  }
  const near = (value, target, scale) => Math.abs(value - target) / scale
  const under = (value, limit, scale) => Math.max(0, value - limit) / scale
  return (
    near(get('sd pitch/yaw/roll', 0), TARGET.sdPitch, 1.2)
    + near(get('sd pitch/yaw/roll', 2), TARGET.sdRoll, 1.6)
    + near(get('sd pitch/yaw/roll', 1), TARGET.sdYaw, 0.5)
    + near(get('ellipse pitch~roll', 0), TARGET.ellipse, 0.06)
    + near(get('ellipse pitch~yaw', 0), TARGET.yawEllipse, 0.35)
    + near(get('path deg/s', 0), TARGET.path, 1.2)
    + near(get('held %', 0), TARGET.held, 12)
    + near(get('episodes /min', 0), TARGET.episodes, 14)
    + near(get('dominant period s', 0), TARGET.period, 6)
    + near(get('episode med dur s', 0), TARGET.episodeDur, 0.5)
    + near(get('episode med peak d/s', 0), TARGET.episodePeak, 1.2)
    + under(get('snap p99 d/s', 0), TARGET.snap, 4)
    + under(get('snap max d/s', 0), TARGET.snap, 5)
  )
}

const candidates = []
for (const degree of [1.75, 1.8, 1.85])
  for (const speed of [[0.42, 0.60], [0.46, 0.64]])
    for (const rest of [[0.4, 1.4], [0.5, 1.9], [0.6, 2.1]])
      for (const creep of [0.26, 0.3, 0.34])
        for (const step of [[0.45, 1.05], [0.55, 1.15]])
          candidates.push({ degree, speed, rest, creep, step })

const work = mkdtempSync(path.join(tmpdir(), 'yxz-sweep-'))
const results = []
for (const candidate of candidates) {
  const text = setConst(source, 'POSTURE_DEGREE', candidate.degree)
  const withSpeed = setConst(text, 'FIGURE_SPEED', `[${candidate.speed.join(', ')}]`)
  const withRest = setConst(withSpeed, 'FIGURE_REST', `[${candidate.rest.join(', ')}]`)
  const withCreep = setConst(withRest, 'FIGURE_CREEP', candidate.creep)
  const withStep = setConst(withCreep, 'FIGURE_STEP', `[${candidate.step.join(', ')}]`)
  const file = path.join(work, 'scene.vue')
  writeFileSync(file, withStep)
  const dump = path.join(work, 'dump')
  try {
    execFileSync(process.execPath, [
      path.join(root, 'scripts/probe_yxz_motion.mjs'),
      '--vrm', vrm,
      '--life', file,
      '--calm', file,
      '--clip', 'YXZ_Idle',
      '--dump', dump,
      '--seconds', String(seconds),
    ], { stdio: 'ignore', cwd: root })
    const compare = execFileSync(process.execPath, [
      path.join(root, 'scripts/compare_yxz_motion_ref.mjs'),
      path.join(root, 'docs/yxz-audit/motion-ref/animation-bare.json'),
      path.join(dump, 'YXZ_Idle.json'),
    ], { encoding: 'utf8', cwd: root })
    const metrics = parseCompare(compare)
    const value = score(metrics)
    results.push({ candidate, value, metrics })
    const sd = metrics['sd pitch/yaw/roll']?.[1] ?? []
    console.log(
      `deg ${candidate.degree}  speed ${candidate.speed.join('-')}  rest ${candidate.rest.join('-')}`
      + `  creep ${candidate.creep}`
      + `  step ${candidate.step.join('-')}`
      + `  score ${value.toFixed(2)}`
      + `  sd ${sd.join('/')}`
      + `  ell ${metrics['ellipse pitch~roll']?.[1]}`
      + `  yaw ${metrics['ellipse pitch~yaw']?.[1]}`
      + `  path ${metrics['path deg/s']?.[1]}`
      + `  held ${metrics['held %']?.[1]}`
      + `  per ${metrics['dominant period s']?.[1]}`
      + `  ep ${metrics['episodes /min']?.[1]}`
      + `  snap ${metrics['snap max d/s']?.[1]}`,
    )
  }
  catch (error) {
    console.log(`candidate failed: ${error.message}`)
  }
}

results.sort((a, b) => a.value - b.value)
console.log('\nbest:')
for (const result of results.slice(0, 5))
  console.log(`  score ${result.value.toFixed(2)}  deg ${result.candidate.degree}`
    + `  speed ${result.candidate.speed.join('-')}  rest ${result.candidate.rest.join('-')}`
    + `  creep ${result.candidate.creep}  step ${result.candidate.step.join('-')}`)

if (!keep)
  rmSync(work, { recursive: true, force: true })
else
  console.log(`\nleft in ${work}`)
