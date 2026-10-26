/**
 * The walk, on its own.
 *
 * The head's idle is a walk between postures, and the walk is the
 * part of the motion that decides whether the figure reads as a person
 * standing and thinking or as a thing rocking on a pivot.  The probe
 * measures the whole figure, which is the right place to judge the
 * result but the wrong place to see why a walk came out wrong.
 *
 * So this prints the two levels the walk produces, the way the figure
 * actually sees them: where the head is, and how fast it got there.
 *
 * Usage:
 *   node scripts/trace_yxz_walk.mjs [scene.vue] [seconds]
 */

import { loadMotionCore } from './lib/vue-motion-core.mjs'

const scene = process.argv[2] ?? 'packages/stage-ui-three/src/components/YXZRealModelScene.vue'
const seconds = Number(process.argv[3] ?? 60)

const attentionShape = { idle: { scale: 1 } }
const smoothstep = value => value * value * (3 - 2 * value)
const THREE = { Vector3: class Vector3 { set(x, y, z) { this.x = x; this.y = y; this.z = z } } }
const motion = new Function('THREE', 'smoothstep', 'ATTENTION_SHAPE', 'HEAD_ROCK_RATIO', `
${loadMotionCore(scene)}
return {
  updateMotionLevels,
  get bodyLevel() { return motionBodyLevel },
  get headLevel() { return motionHeadLevel },
  get neckLevel() { return motionNeckLevel },
}
`)(THREE, smoothstep, attentionShape, 1.378)

const rate = 10
const body = []
const head = []
for (let i = 0; i <= seconds * rate; i++) {
  motion.updateMotionLevels(i / rate)
  body.push(motion.bodyLevel)
  head.push(motion.headLevel)
}

function stats(values) {
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length)
  let path = 0
  for (let i = 1; i < values.length; i++)
    path += Math.abs(values[i] - values[i - 1])
  const sorted = [...values].sort((a, b) => a - b)
  return {
    mean: +mean.toFixed(3),
    sd: +sd.toFixed(3),
    min: +sorted[0].toFixed(3),
    max: +sorted.at(-1).toFixed(3),
    pathPerSec: +(path / seconds).toFixed(3),
  }
}

console.log('body walk', stats(body))
console.log('head walk', stats(head))
console.log('\n  t     body    head')
for (let i = 0; i < body.length; i += rate) {
  console.log(`  ${(i / rate).toFixed(0).padStart(3)}  ${body[i].toFixed(3).padStart(6)}  ${head[i].toFixed(3).padStart(6)}`)
}
