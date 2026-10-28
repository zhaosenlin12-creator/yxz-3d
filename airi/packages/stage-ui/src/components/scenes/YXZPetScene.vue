<script setup lang="ts">
import type { YXZPetFlourish, YXZPetStatus } from '../../composables/use-yxz-pet-motion'

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import armUrl from '../../assets/yxz/layers/arm.png'
import bodyUrl from '../../assets/yxz/layers/body.png'
import eyeLUrl from '../../assets/yxz/layers/eye_l.png'
import eyeRUrl from '../../assets/yxz/layers/eye_r.png'
import glowUrl from '../../assets/yxz/layers/glow.png'
import manifest from '../../assets/yxz/layers/manifest.json'
import mouthOUrl from '../../assets/yxz/layers/mouth_o.png'
import mouthSmallUrl from '../../assets/yxz/layers/mouth_small.png'
import mouthSmileUrl from '../../assets/yxz/layers/mouth_smile.png'
import mouthTalkAUrl from '../../assets/yxz/layers/mouth_talk_a.png'
import mouthTalkBUrl from '../../assets/yxz/layers/mouth_talk_b.png'
import mouthTalkCUrl from '../../assets/yxz/layers/mouth_talk_c.png'
import mouthWideUrl from '../../assets/yxz/layers/mouth_wide.png'
import socketUrl from '../../assets/yxz/layers/socket.png'

import { createYXZPetMotion } from '../../composables/use-yxz-pet-motion'

export type { YXZPetStatus }

const props = withDefaults(defineProps<{
  status?: YXZPetStatus
  /**
   * A one-off action to play.  Change the value to fire it: the same
   * action fires again when the value changes to something else and
   * back, so a caller can wave as often as it likes.
   */
  action?: YXZPetFlourish | ''
  speakingLevel?: number
  paused?: boolean
  focusAt?: { x: number, y: number }
  xOffset?: number | string
  yOffset?: number | string
  scale?: number
  message?: string
}>(), {
  status: 'idle',
  action: '',
  speakingLevel: 0,
  paused: false,
  xOffset: 0,
  yOffset: 0,
  scale: 1,
  message: '',
})

const emit = defineEmits<{
  error: [error: unknown]
}>()

const WHITESPACE_RE = /\s+/g

// The artwork the character is cut from.  Every layer is placed in this
// space, so the numbers come from the cut itself and cannot drift away
// from the pictures they belong to.
interface LayerBox { file: string, x: number, y: number, w: number, h: number, cx: number, cy: number }
interface ArmBox { file: string, x: number, y: number, w: number, h: number, pivotX: number, pivotY: number, handX: number, handY: number }
interface RectBox { file: string, x: number, y: number, w: number, h: number }

const cut = manifest as unknown as {
  width: number
  height: number
  layers: {
    eyes: LayerBox[]
    mouths: LayerBox[]
    glow: RectBox
    arm: ArmBox
  }
}

const ART_W = cut.width
const ART_H = cut.height
const EYES = cut.layers.eyes
const MOUTH = cut.layers.mouths[0]
const GLOW = cut.layers.glow
// The raised arm is a picture of its own so that it can be turned around
// the shoulder.  The pivot is the hinge the arm turns on, and the hand
// anchor is the middle of the palm, which is where the sparkles of a
// wave come from.
const ARM = cut.layers.arm
// Where the feet are, which is what the figure stands on and what the
// breathing and the sway turn about.
const PIVOT_X = ART_W / 2
const PIVOT_Y = ART_H * 0.995

// How far the eyes travel, in picture pixels, at the edge of their reach.
const GAZE_X = 26
const GAZE_Y = 18

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })

const activeLabel = computed(() => ({
  idle: '你好，我是宜小智，想做什么？',
  listening: '我在认真听你的想法',
  thinking: '我正在理解并整理方案',
  speaking: '我来向你介绍这份方案',
  processing: '我正在生成预览和 3D 模型',
  success: '方案完成，可以继续编辑或下载',
}[props.status]))
// The bubble follows the answer: while the assistant is replying it shows a
// short excerpt of what was actually said, so the visitor can read the reply
// without moving their eyes from the character.
const bubbleText = computed(() => {
  const spoken = (props.message ?? '').replace(WHITESPACE_RE, ' ').trim()
  if (!spoken)
    return activeLabel.value
  return spoken.length > 46 ? `${spoken.slice(0, 46)}…` : spoken
})
const isSpeaking = computed(() => props.status === 'speaking')

const canvasContainer = ref<HTMLDivElement>()
const canvas = ref<HTMLCanvasElement>()

const sources: Record<string, string> = {
  body: bodyUrl,
  arm: armUrl,
  socket: socketUrl,
  glow: glowUrl,
  [EYES[0].file]: eyeLUrl,
  [EYES[1].file]: eyeRUrl,
  mouth_smile: mouthSmileUrl,
  mouth_talk_a: mouthTalkAUrl,
  mouth_talk_b: mouthTalkBUrl,
  mouth_talk_c: mouthTalkCUrl,
  mouth_o: mouthOUrl,
  mouth_wide: mouthWideUrl,
  mouth_small: mouthSmallUrl,
}

const images = new Map<string, HTMLImageElement>()
// The action layer.  The channels it owns are added on top of the
// breathing pose in every frame.
const motion = createYXZPetMotion()
// The channels the renderer reads every frame.  They live here rather
// than inside the drawing call so that the helpers above and below can
// all reach them.
const channels = motion.channels
let frame = 0
let running = true
let clock = 0
let lastAt = 0
let entrance = 0

// The gaze the eyes are heading for, and the gaze they are at.
let gazeTarget = { x: 0, y: 0 }
const gaze = { x: 0, y: 0 }
// The head's own answer to the gaze: it is slower, and it is smaller,
// which is what makes the eyes look like they are leading.
const head = { x: 0, y: 0 }
// The blink: it closes, holds, opens, and is timed like a blink.
let blinkAt = 1.6
let blinkPhase = 0
let blinkDepth = 1
let lastPointerAt = -10

// The arm trails the twist of the body: when the figure turns, the arm
// catches up a moment later.  That lag is what gives the picture weight,
// and it costs one spring.
const armFollow = { angle: 0, velocity: 0 }

// The sparkles a waving hand throws off.
interface Sparkle { x: number, y: number, vx: number, vy: number, life: number, size: number }
const sparkles: Sparkle[] = []

// The sparkle art is built once into two small offscreen pictures and
// then stamped into the frame, so a wave never costs more than a pair
// of drawImage calls per sparkle.
let sparkleHalo: HTMLCanvasElement | undefined
let sparkleStar: HTMLCanvasElement | undefined

function buildSparkleArt() {
  const size = 64
  const half = size / 2

  const halo = document.createElement('canvas')
  halo.width = size
  halo.height = size
  const haloContext = halo.getContext('2d')
  if (haloContext) {
    const glow = haloContext.createRadialGradient(half, half, 0, half, half, half)
    glow.addColorStop(0, 'rgba(255, 255, 255, 0.9)')
    glow.addColorStop(0.3, 'rgba(170, 240, 255, 0.42)')
    glow.addColorStop(1, 'rgba(150, 225, 255, 0)')
    haloContext.fillStyle = glow
    haloContext.fillRect(0, 0, size, size)
  }
  sparkleHalo = halo

  const star = document.createElement('canvas')
  star.width = size
  star.height = size
  const starContext = star.getContext('2d')
  if (starContext) {
    // A four-pointed star.  It is drawn in a strong blue so that it
    // still reads against the white glove it comes off.
    starContext.fillStyle = '#3fd2ff'
    starContext.beginPath()
    for (let point = 0; point < 4; point++) {
      const outer = (Math.PI / 2) * point - Math.PI / 2
      const inner = outer + Math.PI / 4
      starContext.lineTo(half + Math.cos(outer) * half * 0.94, half + Math.sin(outer) * half * 0.94)
      starContext.lineTo(half + Math.cos(inner) * half * 0.24, half + Math.sin(inner) * half * 0.24)
    }
    starContext.closePath()
    starContext.fill()
    // The white core keeps the star from looking flat.
    starContext.fillStyle = 'rgba(255, 255, 255, 0.95)'
    starContext.beginPath()
    starContext.arc(half, half, half * 0.2, 0, Math.PI * 2)
    starContext.fill()
  }
  sparkleStar = star
}

/**
 * How far the arm is turned at this moment.
 *
 * Three things add up: the pose the status asks for, the lag that
 * follows the body, and a small sway so the arm is never quite still.
 */
function armAngle() {
  return channels.armRot + armFollow.angle + Math.sin(clock * 0.73) * 0.018
}

/** Where the middle of the palm is once the arm has turned. */
function handPosition(angle: number) {
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  const hx = ARM.handX - ARM.pivotX
  const hy = ARM.handY - ARM.pivotY
  return { x: ARM.pivotX + hx * cos - hy * sin, y: ARM.pivotY + hx * sin + hy * cos }
}

function clamp(value: number, low: number, high: number) {
  return value < low ? low : value > high ? high : value
}

function stageOffsetFraction(value: number | string | undefined, basis: number) {
  if (typeof value === 'number')
    return Number.isFinite(value) ? value / 100 : 0
  const text = String(value ?? '').trim()
  if (!text)
    return 0
  const amount = Number.parseFloat(text)
  if (!Number.isFinite(amount))
    return 0
  if (text.endsWith('%'))
    return amount / 100
  if (text.endsWith('px'))
    return amount / Math.max(1, basis)
  return amount / 100
}

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error(`could not load ${url}`))
    image.src = url
  })
}

// The face each state wears.  The eyes narrow a little when the
// character is thinking and more when it is pleased, and the mouth
// changes with what it is doing.
function faceFor(status: YXZPetStatus) {
  switch (status) {
    case 'listening':
      return { eye: 1, mouth: 'mouth_small' }
    case 'thinking':
      return { eye: 0.76, mouth: 'mouth_o' }
    case 'speaking':
      return { eye: 1, mouth: 'mouth_talk_a' }
    case 'processing':
      return { eye: 0.94, mouth: 'mouth_talk_c' }
    case 'success':
      return { eye: 0.46, mouth: 'mouth_wide' }
    default:
      return { eye: 1, mouth: 'mouth_smile' }
  }
}

const TALK_FRAMES = ['mouth_talk_a', 'mouth_talk_b', 'mouth_talk_c']

/**
 * The sparkles that come off a waving hand.
 *
 * They are little four-pointed stars, drawn additively so that they read
 * as light rather than as paint.
 */
function drawSparkles(context: CanvasRenderingContext2D) {
  if (!sparkles.length || !sparkleHalo || !sparkleStar)
    return
  context.save()
  for (const sparkle of sparkles) {
    const fade = Math.max(0, Math.min(1, sparkle.life))
    // The star grows as it brightens, which is what makes a burst read
    // as a burst rather than as a set of dots.
    const size = sparkle.size * (0.5 + fade * 0.5)
    // The halo is added on top of whatever is behind it.
    context.globalCompositeOperation = 'lighter'
    context.globalAlpha = fade * 0.8
    const haloSize = size * 3.4
    context.drawImage(sparkleHalo, sparkle.x - haloSize / 2, sparkle.y - haloSize / 2, haloSize, haloSize)
    // The star itself is painted, so that it reads on a white glove.
    context.globalCompositeOperation = 'source-over'
    context.globalAlpha = Math.min(1, fade * 1.15)
    context.drawImage(sparkleStar, sparkle.x - size, sparkle.y - size, size * 2, size * 2)
  }
  context.restore()
}

function draw() {
  const element = canvas.value
  const context = element?.getContext('2d')
  if (!element || !context)
    return

  const rect = element.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width))
  const height = Math.max(1, Math.round(rect.height))
  const ratio = Math.min(2, window.devicePixelRatio || 1)
  if (element.width !== width * ratio || element.height !== height * ratio) {
    element.width = width * ratio
    element.height = height * ratio
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, width, height)

  const body = images.get('body')
  if (!body)
    return

  // Where the character stands.  It is fitted to the stage the same way
  // for every screen, and the stage's own zoom and nudge are applied on
  // top of it.
  const zoom = Math.max(0.1, props.scale || 1)
  const base = Math.min(height / ART_H * 0.8, width * 0.92 / ART_W)
  const size = base * zoom
  // The stage's nudge.  A positive offset moves the figure to the left,
  // which is what the panel on the right of the page needs.
  const offsetX = stageOffsetFraction(props.xOffset, width) * width
  const offsetY = -stageOffsetFraction(props.yOffset, height) * height
  // The figure stands on the bottom of the stage and grows upward out of
  // it, the same way the model did.
  const originX = width / 2 + offsetX - (ART_W * size) / 2
  const originY = height * 0.98 + offsetY - ART_H * size

  // --- the figure --------------------------------------------------------
  const breath = Math.sin(clock * 1.85)
  const sway = Math.sin(clock * 0.61)
  const bob = Math.sin(clock * 0.9) * 3
  const entranceScale = entrance < 1 ? 0.86 + 0.14 * entrance : 1
  // The mouth drives the body: while the character is speaking it rides
  // its own voice a little.
  const mouthOpen = props.status === 'speaking'
    ? Math.min(1, Math.max(0, props.speakingLevel))
    : 0
  // While the character talks the body keeps time with its own voice: a
  // small bounce on every syllable is what makes it read as speaking
  // rather than as a still picture with a moving mouth.
  const talkBounce = props.status === 'speaking'
    ? Math.sin(clock * 6.4) * 2.6 * mouthOpen
    : 0
  // A fine tremor while work is running.
  const shakeX = channels.shake > 0 ? (Math.random() - 0.5) * channels.shake : 0

  context.save()
  context.translate(
    originX + PIVOT_X * size + (channels.lean + shakeX) * size,
    originY + PIVOT_Y * size + (bob + channels.lift + mouthOpen * 4 + talkBounce) * size,
  )
  context.rotate(sway * 0.011 + channels.bodyRot)
  context.scale(
    size * entranceScale * (1 - breath * 0.006) * channels.squashX,
    size * entranceScale * (1 + breath * 0.011) * channels.squashY,
  )
  context.translate(-PIVOT_X, -PIVOT_Y)

  context.drawImage(body, 0, 0, ART_W, ART_H)

  // --- the raised arm ----------------------------------------------------
  // The arm turns on the hinge in the shoulder.  It is drawn over the
  // body and under the cap that rides with it, and the cap is cut from
  // the same pixels as the arm, so the joint can never open up.
  const armImage = images.get('arm')
  if (armImage) {
    const angle = armAngle()
    context.save()
    context.translate(ARM.pivotX, ARM.pivotY)
    context.rotate(angle)
    context.translate(-ARM.pivotX, -ARM.pivotY)
    context.drawImage(armImage, ARM.x, ARM.y, ARM.w, ARM.h)
    const socketImage = images.get('socket')
    if (socketImage)
      context.drawImage(socketImage, ARM.x, ARM.y, ARM.w, ARM.h)
    context.restore()
    drawSparkles(context)
  }

  // --- the halo ----------------------------------------------------------
  // The ring is welded into the body layer: the helmet is one whole
  // piece, so nothing can ever tear a seam open between the head and
  // the light above it, however the figure moves.  What still moves on
  // its own is the light the ring throws -- a soft glow laid over the
  // picture, breathing.
  const glow = images.get('glow')
  if (glow) {
    const haloGlow = 0.5 + 0.5 * Math.sin(clock * 1.55)
    context.save()
    context.globalCompositeOperation = 'lighter'
    context.globalAlpha = Math.max(0, Math.min(1, 0.28 + 0.62 * haloGlow + channels.glow * 0.5))
    context.drawImage(glow, GLOW.x, GLOW.y, GLOW.w, GLOW.h)
    context.restore()
  }

  // The face rides a little further than the body does, which is what
  // gives the head its own, slower answer to the pointer.
  const face = faceFor(props.status)
  const eyeScale = face.eye * blinkDepth * channels.eyeOpen
  const talkFrame = TALK_FRAMES[Math.floor(clock * 9) % TALK_FRAMES.length]
  const mouthName = props.status === 'speaking'
    ? (props.speakingLevel > 0.05 ? talkFrame : 'mouth_smile')
    : face.mouth

  for (const eye of EYES) {
    const image = images.get(eye.file)
    if (!image)
      continue
    const dx = gaze.x * GAZE_X + head.x * 7 + channels.gazeBiasX * GAZE_X + channels.faceOffsetX
    const dy = gaze.y * GAZE_Y + head.y * 5 + channels.gazeBiasY * GAZE_Y + channels.faceOffsetY
    context.save()
    context.translate(eye.cx + dx, eye.cy + dy)
    context.scale(1, Math.max(0.04, eyeScale))
    context.drawImage(image, -eye.w / 2, -eye.h / 2, eye.w, eye.h)
    context.restore()
  }

  const mouthImage = images.get(mouthName)
  if (mouthImage) {
    const dx = gaze.x * GAZE_X * 0.35 + head.x * 4 + channels.gazeBiasX * GAZE_X * 0.35 + channels.faceOffsetX
    const dy = gaze.y * GAZE_Y * 0.35 + head.y * 3 + channels.gazeBiasY * GAZE_Y * 0.35 + channels.faceOffsetY + mouthOpen * 3
    context.save()
    context.translate(MOUTH.cx + dx, MOUTH.cy + dy)
    context.drawImage(mouthImage, -MOUTH.w / 2, -MOUTH.h / 2, MOUTH.w, MOUTH.h)
    context.restore()
  }
  context.restore()
}

function tick(at: number) {
  if (!running)
    return
  const dt = lastAt ? Math.min(0.05, (at - lastAt) / 1000) : 0
  lastAt = at
  if (!props.paused) {
    clock += dt
    if (entrance < 1)
      entrance = Math.min(1, entrance + dt * 1.6)

    // The arm trails the body.
    //
    // The picture of the arm is drawn inside the body's own rotation,
    // so the lag has to be *subtracted*: the spring is pulled towards
    // a part of the body's turn and only catches up a beat later.  A
    // limb that turned with the body would look welded down; a limb
    // that lags looks like it has weight of its own.
    const bodyTurn = channels.bodyRot + Math.sin(clock * 0.61) * 0.011
    const armTarget = -bodyTurn * 0.6
    armFollow.velocity += ((armTarget - armFollow.angle) * 62 - armFollow.velocity * 11) * dt
    armFollow.angle += armFollow.velocity * dt

    // The sparkles a waving hand throws off.  They are born at the
    // palm, drift outwards, and fall away under their own weight.
    if (channels.handSpark > 0.04 && Math.random() < channels.handSpark * 0.32) {
      const hand = handPosition(armAngle())
      const spread = (Math.random() - 0.5) * 40
      // The burst leans away from the body, so the sparkles clear the
      // glove instead of sitting on top of it.
      const heading = (Math.random() - 0.5) * Math.PI * 1.5 - 0.35
      const speed = 55 + Math.random() * 90
      sparkles.push({
        x: hand.x + spread,
        y: hand.y + spread * 0.6,
        vx: Math.cos(heading) * speed,
        vy: Math.sin(heading) * speed - 24,
        life: 0.5 + Math.random() * 0.5,
        size: 8 + Math.random() * 9,
      })
      if (sparkles.length > 26)
        sparkles.splice(0, sparkles.length - 26)
    }
    for (let index = sparkles.length - 1; index >= 0; index--) {
      const sparkle = sparkles[index]
      sparkle.life -= dt
      sparkle.x += sparkle.vx * dt
      sparkle.y += sparkle.vy * dt
      sparkle.vy += 70 * dt
      if (sparkle.life <= 0)
        sparkles.splice(index, 1)
    }
  }

  // Where the eyes should be looking.
  const focus = props.focusAt
  let wanted = { x: 0, y: 0 }
  if (focus && typeof focus.x === 'number' && typeof focus.y === 'number') {
    const element = canvas.value
    if (element) {
      const rect = element.getBoundingClientRect()
      // The pointer arrives in the page's own pixels, the same way the
      // Live2D stage takes it.  A pair of numbers inside the unit square
      // is taken as a share of the page instead, so both readings work.
      const normalised = focus.x <= 1 && focus.y <= 1
      const px = normalised ? focus.x * window.innerWidth - rect.left : focus.x - rect.left
      const py = normalised ? focus.y * window.innerHeight - rect.top : focus.y - rect.top
      const faceX = rect.width / 2
      const faceY = rect.height * 0.32
      const dx = px - faceX
      const dy = py - faceY
      const len = Math.hypot(dx, dy)
      if (len > 1) {
        const reach = Math.min(1, len / 420)
        wanted = { x: clamp((dx / len) * reach, -1, 1), y: clamp((dy / len) * reach * 0.7, -1, 1) }
        lastPointerAt = clock
      }
    }
  }
  // With nobody pointing, the eyes drift instead of sitting still.
  if (clock - lastPointerAt > 2.2) {
    const t = clock - lastPointerAt
    wanted = {
      x: Math.sin(t * 0.43) * 0.45 + Math.sin(t * 0.19) * 0.2,
      y: Math.sin(t * 0.31 + 1.4) * 0.22,
    }
  }
  gazeTarget = wanted

  // The eyes answer first, the head follows half a beat later.
  const eyeStep = 1 - Math.exp(-dt * 7.5)
  const headStep = 1 - Math.exp(-dt * 3.1)
  gaze.x += (gazeTarget.x - gaze.x) * eyeStep
  gaze.y += (gazeTarget.y - gaze.y) * eyeStep
  head.x += (gaze.x - head.x) * headStep
  head.y += (gaze.y - head.y) * headStep

  // The blink.
  blinkPhase += dt
  if (blinkPhase > blinkAt) {
    blinkPhase = 0
    blinkAt = 2.4 + Math.random() * 3.4
    if (Math.random() < 0.22)
      blinkAt = 0.16
  }
  const closing = blinkPhase < 0.09
  const holding = blinkPhase >= 0.09 && blinkPhase < 0.15
  const opening = blinkPhase >= 0.15 && blinkPhase < 0.27
  // A blink closes the eye to a slit and not to nothing: the light on
  // the visor is the character, and a character that blinks out of
  // existence for a moment reads as a fault.
  const CLOSED = 0.13
  if (closing)
    blinkDepth = CLOSED + (1 - blinkPhase / 0.09) * (1 - CLOSED)
  else if (holding)
    blinkDepth = CLOSED
  else if (opening)
    blinkDepth = CLOSED + (blinkPhase - 0.15) / 0.12 * (1 - CLOSED)
  else
    blinkDepth = 1

  draw()
  frame = requestAnimationFrame(tick)
}

let observer: ResizeObserver | undefined

onMounted(async () => {
  componentState.value = 'loading'
  buildSparkleArt()
  try {
    await Promise.all(Object.entries(sources).map(async ([name, url]) => {
      images.set(name, await loadImage(url))
    }))
  }
  catch (error) {
    emit('error', error)
    componentState.value = 'pending'
    return
  }
  componentState.value = 'mounted'
  motion.setStatus(props.status)
  observer = new ResizeObserver(() => draw())
  if (canvasContainer.value)
    observer.observe(canvasContainer.value)
  frame = requestAnimationFrame(tick)
})

onUnmounted(() => {
  running = false
  cancelAnimationFrame(frame)
  observer?.disconnect()
  motion.destroy()
})

watch(() => props.status, (status) => {
  lastPointerAt = -10
  motion.setStatus(status)
})

// An action fires when the value changes.  Setting it back to nothing in
// between lets the very same action be fired again.
watch(() => props.action, (action) => {
  if (action)
    motion.play(action)
})

watch(() => props.paused, (paused) => {
  if (paused)
    motion.pause()
  else
    motion.resume()
}, { immediate: true })
</script>

<template>
  <div ref="canvasContainer" class="yxz-pet-scene" :data-status="props.status" aria-label="宜小智">
    <div class="yxz-pet-bubble" role="status" aria-live="polite">
      <span class="yxz-pet-dot" />
      <span class="yxz-pet-bubble-text">{{ bubbleText }}</span>
      <span v-if="isSpeaking" class="yxz-pet-voice-dots" aria-hidden="true">
        <i /><i /><i />
      </span>
    </div>
    <canvas ref="canvas" class="yxz-pet-canvas" />
  </div>
</template>

<style scoped>
.yxz-pet-scene { position: relative; width: 100%; height: 100%; overflow: hidden; }
.yxz-pet-canvas { display: block; width: 100%; height: 100%; }

.yxz-pet-bubble {
  position: absolute;
  top: 4%;
  left: 50%;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: .5rem;
  max-width: min(30rem, calc(100% - 2rem));
  padding: .5rem .85rem;
  border: 1px solid rgba(27, 111, 177, .22);
  border-radius: .7rem;
  background: rgba(255, 255, 255, .9);
  color: #15547c;
  box-shadow: 0 6px 20px rgba(27, 111, 177, .12);
  font-size: .82rem;
  transform: translateX(-50%);
}

/*
 * On wide screens the chat panel is pinned to the right half of the stage
 * while the pet canvas keeps the full width, so a bubble centred on the
 * canvas would slide under the chat.  Pull it back over the robot instead.
 */
@media (min-width: 1024px) {
  .yxz-pet-bubble {
    left: 30%;
    top: 15%;
    max-width: min(24rem, calc(52% - 2rem));
  }
}

.yxz-pet-bubble-text {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  line-height: 1.35;
  text-align: left;
}

.yxz-pet-dot {
  width: .5rem;
  height: .5rem;
  border-radius: 50%;
  background: #18a8e0;
  box-shadow: 0 0 0 4px rgba(24, 168, 224, .12);
}

.yxz-pet-scene[data-status="thinking"] .yxz-pet-dot,
.yxz-pet-scene[data-status="processing"] .yxz-pet-dot {
  background: #7c72ff;
  box-shadow: 0 0 0 4px rgba(124, 114, 255, .14);
}

.yxz-pet-scene[data-status="speaking"] .yxz-pet-dot {
  background: #18b8a4;
  box-shadow: 0 0 0 4px rgba(24, 184, 164, .14);
}

.yxz-pet-scene[data-status="success"] .yxz-pet-dot {
  background: #2bb673;
  box-shadow: 0 0 0 4px rgba(43, 182, 115, .14);
}

.yxz-pet-voice-dots {
  display: inline-flex;
  align-items: center;
  gap: .18rem;
  height: 1rem;
  margin-left: .15rem;
}

.yxz-pet-voice-dots i {
  width: .5rem;
  height: .38rem;
  border-radius: 999px;
  background: #18a8e0;
  animation: yxz-pet-voice-dot .7s ease-in-out infinite alternate;
}

.yxz-pet-voice-dots i:nth-child(2) { animation-delay: .16s; }
.yxz-pet-voice-dots i:nth-child(3) { animation-delay: .32s; }

@keyframes yxz-pet-voice-dot {
  from { transform: scaleY(.55); opacity: .52; }
  to { transform: scaleY(1.35); opacity: 1; }
}
</style>
