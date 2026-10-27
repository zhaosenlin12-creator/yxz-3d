<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

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

export type YXZPetStatus
  = | 'idle'
    | 'listening'
    | 'thinking'
    | 'speaking'
    | 'processing'
    | 'success'

// The artwork the character is cut from.  Every layer is placed in this
// space, so the numbers come from the cut itself and cannot drift away
// from the pictures they belong to.
interface LayerBox { file: string, x: number, y: number, w: number, h: number, cx: number, cy: number }
interface RectBox { file: string, x: number, y: number, w: number, h: number }

const props = withDefaults(defineProps<{
  status?: YXZPetStatus
  speakingLevel?: number
  paused?: boolean
  focusAt?: { x: number, y: number }
  xOffset?: number | string
  yOffset?: number | string
  scale?: number
}>(), {
  status: 'idle',
  speakingLevel: 0,
  paused: false,
  xOffset: 0,
  yOffset: 0,
  scale: 1,
})

const emit = defineEmits<{
  error: [error: unknown]
}>()

const cut = manifest as unknown as {
  width: number
  height: number
  layers: {
    eyes: LayerBox[]
    mouths: LayerBox[]
    glow: RectBox
  }
}

const ART_W = cut.width
const ART_H = cut.height
const EYES = cut.layers.eyes
const MOUTH = cut.layers.mouths[0]
const GLOW = cut.layers.glow
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
const isSpeaking = computed(() => props.status === 'speaking')

const canvasContainer = ref<HTMLDivElement>()
const canvas = ref<HTMLCanvasElement>()

const sources: Record<string, string> = {
  body: bodyUrl,
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

  context.save()
  context.translate(originX + PIVOT_X * size, originY + PIVOT_Y * size + bob)
  context.rotate(sway * 0.011)
  context.scale(
    size * entranceScale * (1 - breath * 0.006),
    size * entranceScale * (1 + breath * 0.011),
  )
  context.translate(-PIVOT_X, -PIVOT_Y)

  context.drawImage(body, 0, 0, ART_W, ART_H)

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
    context.globalAlpha = 0.28 + 0.62 * haloGlow
    context.drawImage(glow, GLOW.x, GLOW.y, GLOW.w, GLOW.h)
    context.restore()
  }

  // The face rides a little further than the body does, which is what
  // gives the head its own, slower answer to the pointer.
  const face = faceFor(props.status)
  const eyeScale = face.eye * blinkDepth
  const talkFrame = TALK_FRAMES[Math.floor(clock * 9) % TALK_FRAMES.length]
  const mouthName = props.status === 'speaking'
    ? (props.speakingLevel > 0.05 ? talkFrame : 'mouth_smile')
    : face.mouth

  for (const eye of EYES) {
    const image = images.get(eye.file)
    if (!image)
      continue
    const dx = gaze.x * GAZE_X + head.x * 7
    const dy = gaze.y * GAZE_Y + head.y * 5
    context.save()
    context.translate(eye.cx + dx, eye.cy + dy)
    context.scale(1, Math.max(0.04, eyeScale))
    context.drawImage(image, -eye.w / 2, -eye.h / 2, eye.w, eye.h)
    context.restore()
  }

  const mouthImage = images.get(mouthName)
  if (mouthImage) {
    const dx = gaze.x * GAZE_X * 0.35 + head.x * 4
    const dy = gaze.y * GAZE_Y * 0.35 + head.y * 3
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
  observer = new ResizeObserver(() => draw())
  if (canvasContainer.value)
    observer.observe(canvasContainer.value)
  frame = requestAnimationFrame(tick)
})

onUnmounted(() => {
  running = false
  cancelAnimationFrame(frame)
  observer?.disconnect()
})

watch(() => props.status, () => {
  lastPointerAt = -10
})
</script>

<template>
  <div ref="canvasContainer" class="yxz-pet-scene" :data-status="props.status" aria-label="宜小智">
    <div class="yxz-pet-bubble" role="status" aria-live="polite">
      <span class="yxz-pet-dot" />
      <span>{{ activeLabel }}</span>
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
  max-width: calc(100% - 2rem);
  padding: .5rem .85rem;
  border: 1px solid rgba(27, 111, 177, .22);
  border-radius: .7rem;
  background: rgba(255, 255, 255, .9);
  color: #15547c;
  box-shadow: 0 6px 20px rgba(27, 111, 177, .12);
  font-size: .82rem;
  transform: translateX(-50%);
  white-space: nowrap;
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
