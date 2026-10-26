<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  imageSrc: string
  caption: string
}>()

const emit = defineEmits<{
  save: [dataUrl: string]
  refine: [dataUrl: string]
  close: []
}>()

interface Point {
  x: number
  y: number
}

interface StrokeOperation {
  kind: 'stroke'
  color: string
  size: number
  points: Point[]
}

interface ShapeOperation {
  kind: 'arrow' | 'circle' | 'rect'
  color: string
  size: number
  start: Point
  end: Point
}

interface TextOperation {
  kind: 'text'
  color: string
  text: string
  x: number
  y: number
}

type Operation = StrokeOperation | ShapeOperation | TextOperation

type Tool = 'brush' | 'arrow' | 'circle' | 'rect'

const canvas = ref<HTMLCanvasElement>()
const brushColor = ref('#ff4d4f')
const brushSize = ref(8)
const textValue = ref('')
const activeTool = ref<Tool>('brush')
const operations = ref<Operation[]>([])
const isDrawing = ref(false)
const imageReady = ref(false)
const imageRect = ref({ x: 0, y: 0, width: 768, height: 768 })
let activeStroke: Operation & { kind: 'stroke' } | undefined
let activeShape: ShapeOperation | undefined
let baseImage: HTMLImageElement | undefined

function drawImage() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx || !imageReady.value || !baseImage)
    return

  ctx.clearRect(0, 0, 768, 768)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, 768, 768)
  const scale = Math.min(768 / baseImage.naturalWidth, 768 / baseImage.naturalHeight)
  imageRect.value = {
    x: (768 - baseImage.naturalWidth * scale) / 2,
    y: (768 - baseImage.naturalHeight * scale) / 2,
    width: baseImage.naturalWidth * scale,
    height: baseImage.naturalHeight * scale,
  }
  ctx.drawImage(baseImage, imageRect.value.x, imageRect.value.y, imageRect.value.width, imageRect.value.height)
  for (const operation of operations.value)
    drawOperation(ctx, operation)
}

function drawArrow(ctx: CanvasRenderingContext2D, start: Point, end: Point, color: string, size: number) {
  ctx.save()
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = size
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(start.x, start.y)
  ctx.lineTo(end.x, end.y)
  ctx.stroke()
  const angle = Math.atan2(end.y - start.y, end.x - start.x)
  const head = Math.max(10, size * 2.4)
  ctx.beginPath()
  ctx.moveTo(end.x, end.y)
  ctx.lineTo(end.x - head * Math.cos(angle - Math.PI / 6), end.y - head * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(end.x - head * Math.cos(angle + Math.PI / 6), end.y - head * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fill()
  ctx.restore()
}

function drawOperation(ctx: CanvasRenderingContext2D, operation: Operation) {
  ctx.save()
  ctx.strokeStyle = operation.color
  ctx.fillStyle = operation.color
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  if (operation.kind === 'stroke') {
    if (operation.points.length < 2) {
      ctx.beginPath()
      ctx.arc(operation.points[0]?.x ?? 0, operation.points[0]?.y ?? 0, operation.size / 2, 0, Math.PI * 2)
      ctx.fill()
    }
    else {
      ctx.lineWidth = operation.size
      ctx.beginPath()
      ctx.moveTo(operation.points[0].x, operation.points[0].y)
      for (const point of operation.points.slice(1))
        ctx.lineTo(point.x, point.y)
      ctx.stroke()
    }
  }
  else if (operation.kind === 'arrow') {
    drawArrow(ctx, operation.start, operation.end, operation.color, operation.size)
  }
  else if (operation.kind === 'circle') {
    ctx.lineWidth = operation.size
    const rx = Math.abs(operation.end.x - operation.start.x) / 2
    const ry = Math.abs(operation.end.y - operation.start.y) / 2
    ctx.beginPath()
    ctx.ellipse(
      (operation.start.x + operation.end.x) / 2,
      (operation.start.y + operation.end.y) / 2,
      Math.max(1, rx), Math.max(1, ry), 0, 0, Math.PI * 2,
    )
    ctx.stroke()
  }
  else if (operation.kind === 'rect') {
    ctx.lineWidth = operation.size
    ctx.strokeRect(
      Math.min(operation.start.x, operation.end.x),
      Math.min(operation.start.y, operation.end.y),
      Math.abs(operation.end.x - operation.start.x),
      Math.abs(operation.end.y - operation.start.y),
    )
  }
  else {
    ctx.font = 'bold 42px sans-serif'
    ctx.shadowColor = 'rgba(255,255,255,.85)'
    ctx.shadowBlur = 5
    ctx.fillText(operation.text, operation.x, operation.y)
  }
  ctx.restore()
}

function redraw() {
  drawImage()
}

function pointFromEvent(event: PointerEvent): Point {
  const rect = canvas.value!.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * 768 / rect.width,
    y: (event.clientY - rect.top) * 768 / rect.height,
  }
}

function startDrawing(event: PointerEvent) {
  if (!canvas.value || !imageReady.value)
    return
  canvas.value.setPointerCapture(event.pointerId)
  const point = pointFromEvent(event)
  if (activeTool.value === 'brush') {
    activeStroke = { kind: 'stroke', color: brushColor.value, size: brushSize.value, points: [point] }
    operations.value.push(activeStroke)
  }
  else {
    activeShape = { kind: activeTool.value, color: brushColor.value, size: brushSize.value, start: point, end: point }
    operations.value.push(activeShape)
  }
  isDrawing.value = true
  redraw()
}

function continueDrawing(event: PointerEvent) {
  if (!isDrawing.value)
    return
  if (activeStroke) {
    activeStroke.points.push(pointFromEvent(event))
    redraw()
    return
  }
  if (activeShape) {
    activeShape.end = pointFromEvent(event)
    redraw()
  }
}

function stopDrawing() {
  isDrawing.value = false
  activeStroke = undefined
  activeShape = undefined
}

function undo() {
  operations.value.pop()
  redraw()
}

function clearEdits() {
  operations.value = []
  redraw()
}

function addText() {
  const text = textValue.value.trim()
  if (!text)
    return
  operations.value.push({ kind: 'text', color: brushColor.value, text: text.slice(0, 18), x: 36, y: 710 })
  textValue.value = ''
  redraw()
}

function applyEdits() {
  if (!canvas.value)
    return
  emit('save', canvas.value.toDataURL('image/png'))
}

function requestRefine() {
  if (!canvas.value)
    return
  emit('refine', canvas.value.toDataURL('image/png'))
}

async function loadImage() {
  imageReady.value = false
  await nextTick()
  const image = new Image()
  image.onload = () => {
    baseImage = image
    imageReady.value = true
    redraw()
  }
  image.onerror = () => {
    baseImage = undefined
    imageReady.value = false
  }
  image.crossOrigin = 'anonymous'
  image.src = props.imageSrc
}

onMounted(loadImage)
watch(() => props.imageSrc, loadImage)
</script>

<template>
  <section class="yxz-canvas-editor" aria-label="宜小智画布编辑器">
    <header class="yxz-canvas-editor-header">
      <div>
        <strong>画布个性化</strong>
        <small>在预览上加标记或文字，再用于 3D 制作</small>
      </div>
      <button type="button" aria-label="关闭画布编辑器" @click="emit('close')">
        ×
      </button>
    </header>

    <div class="yxz-canvas-toolbar">
      <div class="yxz-canvas-tools" role="group" aria-label="批注工具">
        <button type="button" :class="{ active: activeTool === 'brush' }" @click="activeTool = 'brush'">画笔</button>
        <button type="button" :class="{ active: activeTool === 'arrow' }" @click="activeTool = 'arrow'">箭头</button>
        <button type="button" :class="{ active: activeTool === 'circle' }" @click="activeTool = 'circle'">圆圈</button>
        <button type="button" :class="{ active: activeTool === 'rect' }" @click="activeTool = 'rect'">方框</button>
      </div>
      <label>颜色 <input v-model="brushColor" type="color" aria-label="批注颜色"></label>
      <label class="yxz-canvas-size">笔触 <input v-model.number="brushSize" type="range" min="2" max="28" step="2" aria-label="批注粗细"> <span>{{ brushSize }}</span></label>
      <input v-model="textValue" type="text" maxlength="18" placeholder="加一句文字" aria-label="画布文字">
      <button type="button" :disabled="!textValue.trim()" @click="addText">
        加文字
      </button>
      <button type="button" :disabled="!operations.length" @click="undo">
        撤销
      </button>
      <button type="button" :disabled="!operations.length" @click="clearEdits">
        清空
      </button>
    </div>

    <div class="yxz-canvas-frame">
      <canvas
        ref="canvas"
        width="768"
        height="768"
        :aria-label="`${caption}画布，可拖动绘制`"
        @pointerdown="startDrawing"
        @pointermove="continueDrawing"
        @pointerup="stopDrawing"
        @pointercancel="stopDrawing"
        @pointerleave="stopDrawing"
      />
      <span v-if="!imageReady" class="yxz-canvas-loading">正在加载预览…</span>
    </div>

    <footer class="yxz-canvas-editor-footer">
      <span>批注后可直接做 3D，或让 AI 按批注修改一版再检查</span>
      <div class="yxz-canvas-editor-actions">
        <button type="button" :disabled="!imageReady" @click="requestRefine">
          保存并请 AI 按批注修改
        </button>
        <button type="button" :disabled="!imageReady" @click="applyEdits">
          应用到 3D
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.yxz-canvas-editor {
  display: flex;
  flex-direction: column;
  gap: .7rem;
  margin-top: .8rem;
  padding: .8rem;
  border: 1px solid #9fd9ea;
  border-radius: .9rem;
  background: #f5fcff;
}

.yxz-canvas-editor-header,
.yxz-canvas-editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
}

.yxz-canvas-editor-header div {
  display: flex;
  flex-direction: column;
  gap: .15rem;
}

.yxz-canvas-editor-header strong {
  color: #15547c;
  font-size: .84rem;
}

.yxz-canvas-editor-header small,
.yxz-canvas-editor-footer span {
  color: #52758a;
  font-size: .68rem;
}

.yxz-canvas-editor-header button {
  border: 0;
  background: transparent;
  color: #52758a;
  font-size: 1.35rem;
  cursor: pointer;
}

.yxz-canvas-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .4rem;
  color: #52758a;
  font-size: .68rem;
}

.yxz-canvas-toolbar label {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
}

.yxz-canvas-toolbar input[type='color'] {
  width: 1.7rem;
  height: 1.5rem;
  padding: 0;
  border: 0;
  background: transparent;
}

.yxz-canvas-size span {
  width: 1.2rem;
  text-align: right;
}

.yxz-canvas-toolbar input[type='text'] {
  min-width: 7rem;
  flex: 1;
  border: 1px solid #c8e1ec;
  border-radius: .45rem;
  padding: .35rem .45rem;
  color: #234b61;
}

.yxz-canvas-toolbar button,
.yxz-canvas-editor-footer button {
  border: 1px solid #b5dce9;
  border-radius: .45rem;
  background: #fff;
  color: #15547c;
  padding: .35rem .5rem;
  cursor: pointer;
  font-size: .68rem;
}

.yxz-canvas-tools {
  display: inline-flex;
  gap: .25rem;
}

.yxz-canvas-tools button.active {
  border-color: #18a8e0;
  background: #e6f7fd;
  color: #087eae;
}

.yxz-canvas-editor-footer {
  align-items: center;
}

.yxz-canvas-editor-actions {
  display: flex;
  gap: .45rem;
  flex: none;
}

.yxz-canvas-toolbar button:disabled,
.yxz-canvas-editor-footer button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.yxz-canvas-frame {
  position: relative;
  overflow: hidden;
  width: 100%;
  aspect-ratio: 1;
  border: 1px solid #c8e1ec;
  border-radius: .65rem;
  background: #fff;
}

.yxz-canvas-frame canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: crosshair;
  touch-action: none;
}

.yxz-canvas-loading {
  position: absolute;
  inset: 50% auto auto 50%;
  color: #52758a;
  font-size: .75rem;
  transform: translate(-50%, -50%);
}

.yxz-canvas-editor-footer button {
  border-color: #18a8e0;
  background: #18a8e0;
  color: #fff;
}
</style>
