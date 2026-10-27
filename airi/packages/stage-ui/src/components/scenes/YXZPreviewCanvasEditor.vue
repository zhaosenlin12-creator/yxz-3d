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
  size: number
}

type Operation = StrokeOperation | ShapeOperation | TextOperation

type Tool = 'brush' | 'arrow' | 'circle' | 'rect' | 'text'

const CANVAS_SIZE = 1200

const canvas = ref<HTMLCanvasElement>()
const brushColor = ref('#ff4d4f')
const brushSize = ref(8)
const textValue = ref('')
const activeTool = ref<Tool>('brush')
const operations = ref<Operation[]>([])
const isDrawing = ref(false)
const imageReady = ref(false)
const imageError = ref('')
const imageRect = ref({ x: 0, y: 0, width: CANVAS_SIZE, height: CANVAS_SIZE })
const placingText = ref(false)
let activeStroke: Operation & { kind: 'stroke' } | undefined
let activeShape: ShapeOperation | undefined
let baseImage: HTMLImageElement | undefined

function drawImage() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx || !imageReady.value || !baseImage)
    return

  ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)
  const scale = Math.min(CANVAS_SIZE / baseImage.naturalWidth, CANVAS_SIZE / baseImage.naturalHeight)
  imageRect.value = {
    x: (CANVAS_SIZE - baseImage.naturalWidth * scale) / 2,
    y: (CANVAS_SIZE - baseImage.naturalHeight * scale) / 2,
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
    ctx.font = `bold ${operation.size * 6}px "Microsoft YaHei", sans-serif`
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
    x: (event.clientX - rect.left) * CANVAS_SIZE / rect.width,
    y: (event.clientY - rect.top) * CANVAS_SIZE / rect.height,
  }
}

function startDrawing(event: PointerEvent) {
  if (!canvas.value || !imageReady.value)
    return
  // Text tool: click places the text at the exact clicked point.
  if (activeTool.value === 'text') {
    placeTextAt(pointFromEvent(event))
    return
  }
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

// Click anywhere on the canvas to drop a text annotation at that spot.
function placeTextAt(point: Point) {
  if (placingText.value)
    return
  placingText.value = true
  const text = window.prompt('请输入要标注的文字（点在哪，字就加在哪）', textValue.value || '')
  placingText.value = false
  if (!text)
    return
  const clean = text.trim().slice(0, 24)
  if (!clean)
    return
  textValue.value = clean
  operations.value.push({
    kind: 'text',
    color: brushColor.value,
    text: clean,
    x: point.x,
    y: point.y,
    size: Math.max(2, Math.round(brushSize.value / 3)),
  })
  redraw()
}

function undo() {
  operations.value.pop()
  redraw()
}

function clearEdits() {
  operations.value = []
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
  imageError.value = ''
  await nextTick()
  const image = new Image()
  image.onload = () => {
    baseImage = image
    imageReady.value = true
    imageError.value = ''
    redraw()
  }
  image.onerror = () => {
    baseImage = undefined
    imageReady.value = false
    // NOTICE: without this the canvas stayed on "正在加载预览…" forever when
    // the preview image could not be fetched (backend down, session gone),
    // which looked like the page was stuck.
    imageError.value = '预览图加载失败'
  }
  image.crossOrigin = 'anonymous'
  image.src = props.imageSrc
}

onMounted(loadImage)
watch(() => props.imageSrc, loadImage)
</script>

<template>
  <section class="yxz-canvas-editor" aria-label="宜小智画布编辑器">
    <!-- Left vertical toolbar -->
    <aside class="yxz-canvas-toolbar" aria-label="批注工具">
      <div class="yxz-canvas-tools" role="group">
        <button
          v-for="tool in ([
            { id: 'brush', label: '画笔', icon: '✏️' },
            { id: 'arrow', label: '箭头', icon: '↗️' },
            { id: 'circle', label: '圆圈', icon: '⭕' },
            { id: 'rect', label: '方框', icon: '▭' },
            { id: 'text', label: '文字', icon: 'T' },
          ] as const)"
          :key="tool.id"
          type="button"
          :class="{ active: activeTool === tool.id }"
          :title="`${tool.label}${tool.id === 'text' ? '（点击画布即可添加文字）' : ''}`"
          @click="activeTool = tool.id"
        >
          <span class="yxz-tool-icon">{{ tool.icon }}</span>
          <span class="yxz-tool-label">{{ tool.label }}</span>
        </button>
      </div>

      <div class="yxz-canvas-toolbar-divider" />

      <label class="yxz-canvas-color" title="标注颜色">
        <span>颜色</span>
        <input v-model="brushColor" type="color" aria-label="批注颜色">
      </label>

      <label class="yxz-canvas-size" title="线条粗细">
        <span>笔触</span>
        <input v-model.number="brushSize" type="range" min="2" max="28" step="2" aria-label="批注粗细">
        <span class="yxz-canvas-size-value">{{ brushSize }}</span>
      </label>

      <div class="yxz-canvas-toolbar-divider" />

      <button type="button" class="yxz-canvas-mini" :disabled="!operations.length" @click="undo">
        ⟲ 撤销
      </button>
      <button type="button" class="yxz-canvas-mini" :disabled="!operations.length" @click="clearEdits">
        ✕ 清空
      </button>
    </aside>

    <!-- Central canvas -->
    <div class="yxz-canvas-frame">
      <canvas
        ref="canvas"
        :width="CANVAS_SIZE"
        :height="CANVAS_SIZE"
        :aria-label="`${caption}画布，可拖动绘制`"
        @pointerdown="startDrawing"
        @pointermove="continueDrawing"
        @pointerup="stopDrawing"
        @pointercancel="stopDrawing"
        @pointerleave="stopDrawing"
      />
      <span v-if="!imageReady && !imageError" class="yxz-canvas-loading">正在加载预览…</span>
      <span v-if="imageError" class="yxz-canvas-loading yxz-canvas-load-error">
        {{ imageError }}
        <button type="button" class="yxz-canvas-retry" @click="loadImage">重试</button>
      </span>
      <span v-if="activeTool === 'text' && imageReady" class="yxz-canvas-tip">
        点哪里，文字就加在哪里 ✦
      </span>
    </div>

    <!-- Bottom actions -->
    <footer class="yxz-canvas-editor-footer">
      <span class="yxz-canvas-hint">批注后可直接做 3D，或让 AI 按批注修改一版再检查</span>
      <div class="yxz-canvas-editor-actions">
        <button type="button" :disabled="!imageReady" @click="requestRefine">
          保存并请 AI 按批注修改
        </button>
        <button type="button" class="yxz-canvas-primary" :disabled="!imageReady" @click="applyEdits">
          应用批注 → 生成 3D
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.yxz-canvas-editor {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) auto;
  gap: .8rem;
  height: 100%;
  min-height: 560px;
  padding: .9rem;
  border: 1px solid rgba(160, 205, 255, .28);
  border-radius: 1rem;
  background: linear-gradient(165deg, rgba(255, 255, 255, .05) 0%, rgba(255, 255, 255, .02) 100%);
  color: #dceeff;
}

/* Left toolbar */
.yxz-canvas-toolbar {
  display: flex;
  flex-direction: column;
  gap: .45rem;
  padding: .5rem .35rem;
  border-radius: .8rem;
  background: rgba(255, 255, 255, .05);
  border: 1px solid rgba(160, 205, 255, .18);
  align-self: start;
  width: 92px;
}

.yxz-canvas-tools {
  display: flex;
  flex-direction: column;
  gap: .3rem;
}

.yxz-canvas-tools button {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .1rem;
  border: 1px solid transparent;
  border-radius: .6rem;
  background: transparent;
  color: #b9d8f2;
  padding: .4rem .2rem;
  cursor: pointer;
  transition: all .18s ease;
}

.yxz-canvas-tools button:hover {
  background: rgba(255, 255, 255, .09);
  color: #fff;
}

.yxz-canvas-tools button.active {
  border-color: #38b6ff;
  background: rgba(56, 182, 255, .18);
  color: #8fd4ff;
  box-shadow: 0 0 10px rgba(56, 182, 255, .25);
}

.yxz-tool-icon {
  font-size: 1.05rem;
  line-height: 1;
}

.yxz-tool-label {
  font-size: .6rem;
}

.yxz-canvas-toolbar-divider {
  height: 1px;
  margin: .15rem 0;
  background: rgba(160, 205, 255, .18);
}

.yxz-canvas-color,
.yxz-canvas-size {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .25rem;
  font-size: .62rem;
  color: #9fc6e6;
}

.yxz-canvas-color input[type='color'] {
  width: 1.8rem;
  height: 1.35rem;
  padding: 0;
  border: 1px solid rgba(160, 205, 255, .3);
  border-radius: .35rem;
  background: transparent;
  cursor: pointer;
}

.yxz-canvas-size input[type='range'] {
  width: 100%;
  accent-color: #38b6ff;
}

.yxz-canvas-size-value {
  color: #cfe6fb;
}

.yxz-canvas-mini {
  border: 1px solid rgba(160, 205, 255, .25);
  border-radius: .5rem;
  background: rgba(255, 255, 255, .06);
  color: #cfe6fb;
  padding: .3rem .2rem;
  font-size: .62rem;
  cursor: pointer;
}

.yxz-canvas-mini:hover:not(:disabled) {
  background: rgba(255, 255, 255, .12);
}

.yxz-canvas-mini:disabled {
  cursor: not-allowed;
  opacity: .4;
}

/* Central canvas */
.yxz-canvas-frame {
  position: relative;
  overflow: hidden;
  width: 100%;
  aspect-ratio: 1;
  max-height: 100%;
  border: 1px solid rgba(160, 205, 255, .3);
  border-radius: .85rem;
  background: #0a1a2c;
  box-shadow: inset 0 0 40px rgba(0, 0, 0, .35);
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
  color: #9fc6e6;
  font-size: .8rem;
  transform: translate(-50%, -50%);
}

.yxz-canvas-load-error {
  display: flex;
  align-items: center;
  gap: .5rem;
  color: #ffb4b4;
}

.yxz-canvas-retry {
  padding: .2rem .6rem;
  border: 1px solid rgba(255, 180, 180, .45);
  border-radius: .4rem;
  background: rgba(255, 180, 180, .12);
  color: #ffd7d7;
  font-size: .75rem;
  cursor: pointer;
}

.yxz-canvas-tip {
  position: absolute;
  top: .55rem;
  left: 50%;
  transform: translateX(-50%);
  padding: .25rem .7rem;
  border-radius: 999px;
  background: rgba(56, 182, 255, .22);
  border: 1px solid rgba(56, 182, 255, .45);
  color: #a9ddff;
  font-size: .68rem;
  pointer-events: none;
  animation: yxz-tip-breathe 1.6s ease-in-out infinite;
}

@keyframes yxz-tip-breathe {
  0%, 100% { opacity: .75; }
  50% { opacity: 1; }
}

/* Bottom actions */
.yxz-canvas-editor-footer {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  padding-top: .2rem;
}

.yxz-canvas-hint {
  color: #7fa9cc;
  font-size: .68rem;
}

.yxz-canvas-editor-actions {
  display: flex;
  gap: .5rem;
  flex: none;
}

.yxz-canvas-editor-actions button {
  border: 1px solid rgba(160, 205, 255, .4);
  border-radius: .6rem;
  background: rgba(255, 255, 255, .08);
  color: #dceeff;
  padding: .5rem .9rem;
  font-size: .72rem;
  cursor: pointer;
  transition: all .18s ease;
}

.yxz-canvas-editor-actions button:hover:not(:disabled) {
  background: rgba(255, 255, 255, .14);
}

.yxz-canvas-editor-actions .yxz-canvas-primary {
  border-color: #38b6ff;
  background: #1e7fb8;
  color: #fff;
}

.yxz-canvas-editor-actions .yxz-canvas-primary:hover:not(:disabled) {
  background: #2890cf;
}

.yxz-canvas-editor-actions button:disabled {
  cursor: not-allowed;
  opacity: .45;
}
</style>
