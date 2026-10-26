import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { createContext, runInContext } from 'node:vm'

const source = readFileSync('packages/stage-ui-three/src/components/YXZRealModelScene.vue', 'utf8')
const core = source.split('// >>> YXZ MOTION CORE BEGIN')[1].split('// <<< YXZ MOTION CORE END')[0]
const noise = source.slice(source.indexOf('function motionHash('), source.indexOf('// ---------------------------------------------------------------------', source.indexOf('function motionHash(')))
const THREE = await import('../node_modules/.pnpm/three@0.183.2/node_modules/three/build/three.module.js')

function load(seed = 12345) {
  let state = seed
  const math = Object.create(Math)
  math.random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  }
  const context = createContext({
    THREE, Math: math, MOTION_SEED: seed, HEAD_ROCK_RATIO: 1.378,
    ATTENTION_SHAPE: { idle: { scale: 1 } }, ATTENTION_GAIN: { idle: 1 },
    attentionNow: { pitch: 0, yaw: 0, roll: 0 },
    smoothstep: value => {
      const k = Math.max(0, Math.min(1, value))
      return k * k * (3 - 2 * k)
    },
  })
  return runInContext(stripTypeScriptTypes(`${noise}\n${core}
    globalThis.core = {
      allAxes, headYaw, poseStep, poseRedraw, updateMotionLevels, updateHeadShape,
      resetMotion, headGestures, swayHead, gestures: () => headGestureCount,
    }
  `), context)
}

function sampleStep(fps) {
  const motion = load()
  motion.updateMotionLevels(0)
  for (const axis of motion.allAxes)
    axis.next = Infinity
  motion.headYaw.want = 2
  for (let frame = 1; frame <= fps; frame++)
    motion.updateMotionLevels(frame / fps)
  return motion.headYaw.pos
}

const high = sampleStep(120)
const low = sampleStep(10)
console.log({ highFpsPose: high, lowFpsPose: low, difference: Math.abs(high - low) })
assert.ok(Math.abs(high - low) < 0.03, '10Hz and 120Hz must advance the same motion time')

for (const seed of [1, 17, 99, 12345]) {
  const motion = load(seed)
  for (let i = 0; i < 10000; i++) {
    for (const axis of motion.allAxes) {
      motion.poseRedraw(axis, i)
      assert.ok(Math.abs(axis.want) <= axis.limit, 'random targets must stay inside their limit')
    }
  }
  motion.resetMotion()
  const out = new THREE.Quaternion()
  for (let frame = 0; frame < 18000; frame++) {
    const time = frame / 60
    motion.updateMotionLevels(time)
    const before = motion.allAxes.map(axis => axis.pos)
    motion.updateHeadShape(time, 'idle', out, 0, 0, 0)
    assert.deepEqual(motion.allAxes.map(axis => axis.pos), before, 'same frame must not advance twice')
    assert.ok(out.toArray().every(Number.isFinite))
  }
  const rate = motion.gestures() / 5
  assert.ok(rate >= 8 && rate <= 30, `gesture starvation or flooding: ${rate}/min`)
  motion.resetMotion()
  assert.equal(motion.gestures(), 0)
  assert.ok(motion.allAxes.every(axis => axis.pos === 0 && axis.vel === 0))
  console.log({ seed, gesturesPerMinute: rate })
}
console.log('Motion core contracts passed.')
