<script setup lang="ts">
import type { YXZBuildStage, YXZLaserCardResponse, YXZLaserTemplate, YXZModelPart, YXZModelProgress } from '../../../../packages/stage-ui/src/composables/use-yxz-print-preview'

import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import YXZPreviewCanvasEditor from '../../../../packages/stage-ui/src/components/scenes/YXZPreviewCanvasEditor.vue'

import { createYXZCartoonModel, createYXZLaserBackground, createYXZLaserCard, detectYXZLocalSoftware, formatYXZElapsed, getYXZPrintApiBase, listYXZLaserTemplates, listYXZModelParts, openYXZLaserCardInSoftware, resolveYXZBuildStage, YXZ_BUILD_STAGES } from '../../../../packages/stage-ui/src/composables/use-yxz-print-preview'

const route = useRoute()
const sessionId = String(route.query.session ?? '')
const imageIndex = Number(route.query.image ?? 0)
const previewSrc = ref(String(route.query.src ?? ''))
const caption = String(route.query.caption ?? '宜小智创作方案')

interface YXZPresetModel {
  id: string
  name: string
  desc: string
  thumbUrl: string | null
  glbUrl: string
  stlUrl: string | null
  /** Which axis of the file is the height, so the preview can stand it up. */
  upAxis?: string
}

const editedDataUrl = ref('')
const building = ref(false)
const progress = ref<YXZModelProgress | null>(null)
const buildStartedAt = ref(0)
const elapsedMs = ref(0)
const model = ref<{ glbUrl: string, stlUrl: string, upAxis: string } | null>(null)
/** The separate bodies of the current model, for printing them one by one. */
const parts = ref<YXZModelPart[]>([])
const errorMessage = ref('')
const presets = ref<YXZPresetModel[]>([])
const presetsLoading = ref(true)
const presetsError = ref('')
// '2d' = canvas editing, '3d' = model preview (scene switching like Tripo)
const activeView = ref<'2d' | '3d'>('2d')

let elapsedTimer: ReturnType<typeof setInterval> | undefined

const currentStage = computed<YXZBuildStage>(() => progress.value?.stage ?? 'queued')
const stageIndex = computed(() => YXZ_BUILD_STAGES.findIndex(stage => stage.id === currentStage.value))
function stageState(stageId: YXZBuildStage) {
  if (currentStage.value === 'failed')
    return stageIndex.value >= 0 && YXZ_BUILD_STAGES[stageIndex.value].id === stageId ? 'failed' : 'todo'
  if (currentStage.value === 'done')
    return 'done'
  const index = YXZ_BUILD_STAGES.findIndex(stage => stage.id === stageId)
  if (index < 0)
    return 'todo'
  if (index < stageIndex.value)
    return 'done'
  if (index === stageIndex.value)
    return 'active'
  return 'todo'
}

function startElapsedTimer() {
  buildStartedAt.value = Date.now()
  elapsedMs.value = 0
  stopElapsedTimer()
  elapsedTimer = setInterval(() => {
    elapsedMs.value = Date.now() - buildStartedAt.value
  }, 500)
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = undefined
  }
}

// --- Laser-cut card export -------------------------------------------
// The card is the physical end of the chain: its back is the fixed activity
// artwork and its front is the visitor's own model preview.
const laserForm = ref({ name: '', title: '', unit: '', contact: '' })
const laserCard = ref<YXZLaserCardResponse | null>(null)
const laserBusy = ref(false)
const laserError = ref('')
const laserSide = ref<'front' | 'back'>('front')
const laserSoftwareMessage = ref('')
// The card back is generated on request: the visitor describes the look they
// want and the image service paints it.
const laserTemplates = ref<YXZLaserTemplate[]>([])
const laserBackTemplate = ref('activity_stage')
const laserFrontTemplate = ref('')
const laserBackgroundPrompt = ref('')
const laserFrontPrompt = ref('')
const backgroundBusy = ref<'back' | 'front' | ''>('')
const backgroundMessage = ref('')
const backTemplates = computed(() => laserTemplates.value.filter(item => item.side !== 'front'))
const frontTemplates = computed(() => laserTemplates.value.filter(item => item.side === 'front'))
const laserCardImage = computed(() => {
  if (!laserCard.value)
    return ''
  return laserSide.value === 'front' ? laserCard.value.frontUrl : laserCard.value.backUrl
})

async function generateLaserCard() {
  if (laserBusy.value)
    return
  if (!sessionId) {
    laserError.value = '当前页面没有作品会话，请从对话里的预览卡片进入创作面板。'
    return
  }
  laserBusy.value = true
  laserError.value = ''
  try {
    laserCard.value = await createYXZLaserCard({
      sessionId: `${sessionId}_card`,
      artworkSessionId: sessionId,
      artworkImageIndex: imageIndex,
      name: laserForm.value.name,
      title: laserForm.value.title,
      unit: laserForm.value.unit,
      contact: laserForm.value.contact,
      backTemplate: laserBackTemplate.value,
      frontTemplate: laserFrontTemplate.value,
    })
    laserSide.value = 'front'
  }
  catch (error) {
    laserError.value = error instanceof Error ? error.message : '卡片生成失败，请稍后重试'
  }
  finally {
    laserBusy.value = false
  }
}

async function openLaserCardInSoftware() {
  if (!laserCard.value)
    return
  laserSoftwareMessage.value = ''
  try {
    const tools = await detectYXZLocalSoftware()
    const laser = tools.find(tool => tool.kind === 'laser' && tool.available)
    if (!laser) {
      laserSoftwareMessage.value = '未检测到可用的激光切割软件，可先下载 SVG 再手动导入 xTool。'
      return
    }
    await openYXZLaserCardInSoftware(laser.id, laserCard.value.sessionId)
    laserSoftwareMessage.value = `已在 ${laser.name} 中打开切割文件，请确认尺寸与切割参数。`
  }
  catch (error) {
    laserSoftwareMessage.value = error instanceof Error ? error.message : '打开激光软件失败'
  }
}

async function loadPresets() {
  presetsLoading.value = true
  presetsError.value = ''
  try {
    const resp = await fetch(`${getYXZPrintApiBase()}/api/presets/models`)
    if (resp.ok) {
      const data = await resp.json()
      presets.value = Array.isArray(data.items) ? data.items : []
    }
    else {
      presetsError.value = `预制模型加载失败（HTTP ${resp.status}）`
    }
  }
  catch (error) {
    // NOTICE: the backend being down used to hide this section silently, so
    // the four 宜小智 pose cards simply vanished with no explanation.
    presetsError.value = `预制模型加载失败：${error instanceof Error ? error.message : String(error)}`
  }
  finally {
    presetsLoading.value = false
  }
}

async function loadLaserTemplates() {
  try {
    laserTemplates.value = await listYXZLaserTemplates()
  }
  catch { /* the packaged template stays selected */ }
}

async function generateLaserBackground(side: 'back' | 'front' = 'back') {
  if (backgroundBusy.value)
    return
  const description = (side === 'front' ? laserFrontPrompt.value : laserBackgroundPrompt.value).trim()
  if (!description) {
    backgroundMessage.value = side === 'front' ? '先描述一下你想要的正面风格' : '先说说你想要什么样的背景吧'
    return
  }
  backgroundBusy.value = side
  backgroundMessage.value = side === 'front' ? '正在为你绘制卡片正面…' : '正在为你绘制背景…'
  try {
    const template = await createYXZLaserBackground(description, side)
    if (side === 'front')
      laserFrontTemplate.value = template.id
    else
      laserBackTemplate.value = template.id
    await loadLaserTemplates()
    backgroundMessage.value = side === 'front' ? '正面好了，已经选上，可以直接生成卡片' : '背景好了，已经选上，可以直接生成卡片'
    if (laserCard.value)
      await generateLaserCard()
  }
  catch (error) {
    backgroundMessage.value = error instanceof Error ? error.message : '背景生成失败，请稍后重试'
  }
  finally {
    backgroundBusy.value = ''
  }
}

async function loadExistingModel() {
  if (!sessionId)
    return
  try {
    const resp = await fetch(`${getYXZPrintApiBase()}/api/sessions/${encodeURIComponent(sessionId)}/model`)
    if (!resp.ok)
      return
    const data = await resp.json()
    if (!data?.exists || !data?.glb_url)
      return
    model.value = {
      glbUrl: `${getYXZPrintApiBase()}${data.glb_url}`,
      stlUrl: data.stl_url ? `${getYXZPrintApiBase()}${data.stl_url}` : '',
      upAxis: typeof data.up_axis === 'string' ? data.up_axis : 'z',
    }
    progress.value = { percent: 100, message: '已载入本方案此前生成的 3D 模型', step: 'done' }
    void loadParts()
  }
  catch { /* the model simply does not exist yet */ }
}

// The separate bodies of the model, so each of them can be printed on its
// own. A model that is one solid body simply reports a single part.
async function loadParts() {
  if (!sessionId)
    return
  try {
    const result = await listYXZModelParts(sessionId)
    parts.value = result.parts
  }
  catch {
    // The split is an extra: a model without separable bodies must not
    // break the workbench.
    parts.value = []
  }
}

onMounted(() => {
  void loadPresets()
  void loadLaserTemplates()
  void loadExistingModel()
  void loadSessionPreview()
})

// The workbench is usually opened straight from a chat session, which only
// carries the session id. Recover the picture that session produced so the
// canvas editor and the laser card have something to work with.
async function loadSessionPreview() {
  if (previewSrc.value || !sessionId)
    return
  const base = getYXZPrintApiBase()
  try {
    const resp = await fetch(`${base}/api/sessions/${encodeURIComponent(sessionId)}/previews`)
    if (!resp.ok)
      return
    const data = await resp.json()
    const previews = Array.isArray(data?.previews) ? data.previews : []
    const wanted = previews.find((item: { index: number }) => item?.index === imageIndex)
    const fallback = previews[0]
    const picked = wanted ?? fallback
    if (picked?.path)
      previewSrc.value = `${base}${picked.path}`
  }
  catch {
    // A session without previews is normal: the workbench still works, the
    // canvas simply has nothing to edit yet.
  }
}

function presetPreviewUrl(p: YXZPresetModel) {
  return `/yxz-preview?model=${encodeURIComponent(`${getYXZPrintApiBase()}${p.glbUrl}`)}&up=${encodeURIComponent(p.upAxis ?? 'z')}`
}

function partPreviewUrl(part: YXZModelPart) {
  return `/yxz-preview?model=${encodeURIComponent(`${getYXZPrintApiBase()}${part.glb_url}`)}&up=z`
}

function presetStlDownload(p: YXZPresetModel) {
  if (!p.stlUrl)
    return ''
  const url = `${getYXZPrintApiBase()}${p.stlUrl}`
  return `${url}${url.includes('?') ? '&' : '?'}download=1`
}

function onSave(dataUrl: string) {
  editedDataUrl.value = dataUrl
}

function switchView(view: '2d' | '3d') {
  if (view === '3d' && !model.value)
    return
  activeView.value = view
}

async function startModelBuild() {
  if (!sessionId || building.value)
    return
  building.value = true
  errorMessage.value = ''
  model.value = null
  activeView.value = '3d'
  progress.value = { percent: 2, message: '已收到你的方案，马上开始制作…', step: 'building', stage: 'queued' }
  startElapsedTimer()
  try {
    const result = await createYXZCartoonModel({
      sessionId,
      imageIndex,
      ...(editedDataUrl.value ? { customImage: editedDataUrl.value } : {}),
      onProgress: (p) => {
        progress.value = { ...p, stage: p.stage ?? resolveYXZBuildStage(p.step, p.percent) }
      },
    })
    model.value = { glbUrl: result.glbUrl, stlUrl: result.stlUrl, upAxis: 'z' }
    progress.value = { percent: 100, message: '3D 模型已经做好啦，可以预览和下载了', step: 'done', stage: 'done' }
    activeView.value = '3d'
    void loadParts()
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '3D 生成失败，请重试'
    progress.value = { percent: 0, message: errorMessage.value, step: 'failed', stage: 'failed' }
  }
  finally {
    building.value = false
    stopElapsedTimer()
  }
}

const modelPreviewUrl = computed(() => model.value ? `/yxz-preview?model=${encodeURIComponent(model.value.glbUrl)}&up=${encodeURIComponent(model.value.upAxis)}` : '')
const progressPercent = computed(() => progress.value?.percent ?? 0)
const origin = typeof window !== 'undefined' ? window.location.origin : ''

function goBack() {
  if (typeof window !== 'undefined')
    window.close()
}
</script>

<template>
  <div class="yxz-studio">
    <header class="yxz-studio-header">
      <div class="yxz-studio-title">
        <strong>宜小智 · 创作工作室</strong>
        <small>2D 画布自由编辑（画笔 / 图形 / 点哪写哪的文字）→ 一键生成彩色 3D 模型</small>
      </div>
      <div class="yxz-studio-header-actions">
        <a class="yxz-studio-back" :href="origin" @click.prevent="goBack">← 返回对话</a>
        <a v-if="model" class="yxz-studio-open" :href="modelPreviewUrl" target="_blank" rel="noopener noreferrer">打开 3D 预览 ↗</a>
        <a v-if="model" class="yxz-studio-download" :href="`${model.stlUrl}${model.stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL</a>
      </div>
    </header>

    <!-- View switcher: 2D editing <-> 3D model (scene switch, Tripo-style) -->
    <nav class="yxz-studio-views" aria-label="视图切换">
      <button
        type="button"
        :class="{ active: activeView === '2d' }"
        @click="switchView('2d')"
      >
        <span class="yxz-view-icon">✏️</span>
        <span>2D 画布编辑</span>
        <small v-if="editedDataUrl" class="yxz-view-badge">已批注</small>
      </button>
      <button
        type="button"
        :class="{ active: activeView === '3d' }"
        :disabled="!model && !building"
        @click="switchView('3d')"
      >
        <span class="yxz-view-icon">🧊</span>
        <span>3D 模型预览</span>
        <small v-if="model" class="yxz-view-badge">已生成</small>
      </button>
    </nav>

    <!-- Preset printable models (3 poses, built with Tripo / Hunyuan3D) -->
    <section v-if="presets.length || presetsError" class="yxz-studio-presets" aria-label="宜小智预制模型示例">
      <header class="yxz-studio-presets-head">
        <strong>宜小智预制 3D 模型示例</strong>
        <small>可 3D 打印的成品 · 点击预览，可直接下载 STL 交给打印机</small>
        <button v-if="presetsError" type="button" class="yxz-studio-presets-retry" @click="loadPresets">重试</button>
      </header>
      <p v-if="presetsError" class="yxz-studio-presets-error">{{ presetsError }} —— 请确认后端已启动（默认 8000 端口）。</p>
      <div class="yxz-studio-presets-grid">
        <article v-for="p in presets" :key="p.id" class="yxz-studio-preset">
          <a
            class="yxz-studio-preset-thumb"
            :href="presetPreviewUrl(p)"
            target="_blank"
            rel="noopener noreferrer"
            :title="`打开 ${p.name} 3D 预览`"
          >
            <img v-if="p.thumbUrl" :src="`${getYXZPrintApiBase()}${p.thumbUrl}`" :alt="p.name" loading="lazy">
            <span v-else class="yxz-studio-preset-ph">🧊</span>
            <span class="yxz-studio-preset-preview">点开 3D 预览 ↗</span>
          </a>
          <div class="yxz-studio-preset-body">
            <h4>{{ p.name }}</h4>
            <p>{{ p.desc }}</p>
            <div class="yxz-studio-preset-actions">
              <a class="yxz-studio-preset-link" :href="presetPreviewUrl(p)" target="_blank" rel="noopener noreferrer">3D 预览</a>
              <a
                v-if="p.stlUrl"
                class="yxz-studio-preset-link"
                :href="presetStlDownload(p)"
                download
                rel="noreferrer"
              >下载 STL</a>
            </div>
          </div>
        </article>
      </div>
    </section>

    <main class="yxz-studio-main">
      <!-- Central working area -->
      <section v-if="activeView === '2d'" class="yxz-studio-canvas">
        <YXZPreviewCanvasEditor
          :image-src="previewSrc"
          :caption="caption"
          @save="onSave"
          @refine="onSave"
          @close="goBack"
        />
      </section>

      <!-- 3D scene view -->
      <section v-else class="yxz-studio-3d">
        <template v-if="model">
          <iframe
            class="yxz-studio-3d-frame"
            :src="modelPreviewUrl"
            title="宜小智 3D 模型预览"
          />
          <div class="yxz-studio-3d-actions">
            <a :href="modelPreviewUrl" target="_blank" rel="noopener noreferrer">新窗口打开 3D 预览 ↗</a>
            <a :href="`${model.stlUrl}${model.stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL（打印用）</a>
          </div>
          <section v-if="parts.length" class="yxz-studio-parts" aria-label="模型零件拆分">
            <header class="yxz-studio-parts-head">
              <strong>零件拆分</strong>
              <small>这个模型由 {{ parts.length }} 个独立零件组成，可以分别预览和打印</small>
            </header>
            <div class="yxz-studio-parts-grid">
              <article v-for="part in parts" :key="part.index" class="yxz-studio-part">
                <h5>{{ part.name }}</h5>
                <p>{{ part.extents_mm.join(' × ') }} mm · {{ part.faces.toLocaleString('en-US') }} 面</p>
                <div class="yxz-studio-part-actions">
                  <a
                    class="yxz-studio-preset-link"
                    :href="partPreviewUrl(part)"
                    target="_blank"
                    rel="noopener noreferrer"
                  >3D 预览</a>
                  <a
                    class="yxz-studio-preset-link"
                    :href="`${getYXZPrintApiBase()}${part.stl_url}${part.stl_url.includes('?') ? '&' : '?'}download=1`"
                    download
                    rel="noreferrer"
                  >下载 STL</a>
                </div>
              </article>
            </div>
          </section>
        </template>
        <div v-else-if="building" class="yxz-studio-3d-building">
          <div class="yxz-studio-3d-building-preview">
            <img :src="editedDataUrl || previewSrc" :alt="caption">
            <div class="yxz-studio-3d-building-overlay">
              <span class="yxz-studio-3d-building-spinner" />
              <strong>{{ progress?.message || '正在制作 3D 模型，请耐心等待…' }}</strong>
              <small>成品做好后会自动在这里显示 3D 预览</small>
            </div>
          </div>
          <ol class="yxz-studio-stages is-wide">
            <li
              v-for="(stage, index) in YXZ_BUILD_STAGES"
              :key="stage.id"
              :class="[`is-${stageState(stage.id)}`, { 'is-current': index === stageIndex }]"
            >
              <span class="yxz-studio-stage-dot" />
              <div>
                <strong>{{ stage.label }}</strong>
                <small>{{ stage.hint }}</small>
              </div>
            </li>
          </ol>
          <p class="yxz-studio-elapsed">
            已用时 {{ formatYXZElapsed(elapsedMs) }} · 进度 {{ progressPercent }}%
          </p>
        </div>
        <div v-else class="yxz-studio-3d-empty">
          <div class="yxz-studio-3d-empty-icon">
            🧊
          </div>
          <p>先在 2D 画布完成编辑，再点击「生成 3D 模型」</p>
          <button type="button" class="yxz-studio-build" @click="activeView = '2d'">
            返回 2D 编辑
          </button>
        </div>
      </section>

      <!-- Right control panel -->
      <aside class="yxz-studio-side">
        <div class="yxz-studio-card">
          <h3>当前方案</h3>
          <p class="yxz-studio-caption">
            {{ caption }}
          </p>
          <p v-if="editedDataUrl" class="yxz-studio-note">
            ✓ 已应用你的批注编辑，将随模型一起生成
          </p>
        </div>

        <div class="yxz-studio-card">
          <h3>生成 3D 模型</h3>
          <p class="yxz-studio-note">
            按你的设计稿生成可以 3D 打印的立体模型，全程自动完成。
          </p>
          <button
            class="yxz-studio-build"
            :disabled="building || !sessionId"
            @click="startModelBuild"
          >
            {{ building ? '制作中…' : '开始生成 3D 模型' }}
          </button>

          <div v-if="building" class="yxz-studio-progress">
            <div class="yxz-studio-progress-bar">
              <span :style="{ width: `${progressPercent}%` }" />
            </div>
            <p>{{ progress?.message || '正在制作 3D 模型，请耐心等待…' }}</p>
            <ol class="yxz-studio-stages">
              <li
                v-for="(stage, index) in YXZ_BUILD_STAGES"
                :key="stage.id"
                :class="[`is-${stageState(stage.id)}`, { 'is-current': index === stageIndex }]"
              >
                <span class="yxz-studio-stage-dot" />
                <div>
                  <strong>{{ stage.label }}</strong>
                  <small>{{ stage.hint }}</small>
                </div>
              </li>
            </ol>
            <p class="yxz-studio-elapsed">
              已用时 {{ formatYXZElapsed(elapsedMs) }} · 进度 {{ progressPercent }}%
            </p>
          </div>

          <p v-if="errorMessage" class="yxz-studio-error">
            {{ errorMessage }}
          </p>

          <div v-if="model" class="yxz-studio-done">
            <span>✓ 模型已完成</span>
            <button type="button" class="yxz-studio-linkish" @click="switchView('3d')">
              切换到 3D 预览
            </button>
            <a :href="`${model.stlUrl}${model.stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL（打印用）</a>
          </div>
        </div>

        <div class="yxz-studio-card">
          <h3>导出激光切割卡片</h3>
          <p class="yxz-studio-note">
            正面放你的作品预览图，背面是活动主视觉背景，尺寸固定 {{ laserCard?.sizeMm.width ?? 100 }} × {{ laserCard?.sizeMm.height ?? 56.25 }} mm。
          </p>
          <div class="yxz-studio-laser-bg">
            <label class="yxz-studio-laser-bg-label">
              卡片正面主视觉
              <textarea
                v-model="laserFrontPrompt"
                rows="2"
                maxlength="120"
                placeholder="描述正面的风格，例如：明亮蓝紫渐变，电路板与光点，底部留白放名字"
              />
            </label>
            <div class="yxz-studio-laser-bg-actions">
              <button
                type="button"
                class="yxz-studio-linkish"
                :disabled="backgroundBusy !== ''"
                @click="generateLaserBackground('front')"
              >
                {{ backgroundBusy === 'front' ? '正在绘制…' : 'AI 生成正面' }}
              </button>
              <button
                v-if="laserFrontTemplate"
                type="button"
                class="yxz-studio-linkish"
                @click="laserFrontTemplate = ''"
              >
                恢复纯色版式
              </button>
            </div>
            <div v-if="frontTemplates.length" class="yxz-studio-laser-templates">
              <button
                v-for="tpl in frontTemplates"
                :key="tpl.id"
                type="button"
                :class="['yxz-studio-laser-template', { active: laserFrontTemplate === tpl.id }]"
                @click="laserFrontTemplate = tpl.id"
              >
                <img :src="`${getYXZPrintApiBase()}${tpl.url}`" :alt="tpl.name" loading="lazy">
                <span>{{ tpl.name }}</span>
              </button>
            </div>
          </div>
          <div class="yxz-studio-laser-bg">
            <label class="yxz-studio-laser-bg-label">
              卡片背面背景
              <textarea
                v-model="laserBackgroundPrompt"
                rows="2"
                maxlength="120"
                placeholder="描述你想要的背景，例如：深蓝科技感，星辰与电路板，卡通插画风"
              />
            </label>
            <div class="yxz-studio-laser-bg-actions">
              <button
                type="button"
                class="yxz-studio-linkish"
                :disabled="backgroundBusy !== ''"
                @click="generateLaserBackground('back')"
              >
                {{ backgroundBusy === 'back' ? '正在绘制…' : 'AI 生成背景' }}
              </button>
              <span v-if="backgroundMessage" class="yxz-studio-note">{{ backgroundMessage }}</span>
            </div>
            <div v-if="backTemplates.length" class="yxz-studio-laser-templates">
              <button
                v-for="tpl in backTemplates"
                :key="tpl.id"
                type="button"
                :class="['yxz-studio-laser-template', { active: laserBackTemplate === tpl.id }]"
                @click="laserBackTemplate = tpl.id"
              >
                <img :src="`${getYXZPrintApiBase()}${tpl.url}`" :alt="tpl.name" loading="lazy">
                <span>{{ tpl.name }}</span>
              </button>
            </div>
          </div>
          <div class="yxz-studio-laser-fields">
            <label>姓名 <input v-model="laserForm.name" maxlength="12" placeholder="张三"></label>
            <label>身份 <input v-model="laserForm.title" maxlength="20" placeholder="学生"></label>
            <label>学校 <input v-model="laserForm.unit" maxlength="30" placeholder="宜昌市实验中学"></label>
            <label>联系方式 <input v-model="laserForm.contact" maxlength="60" placeholder="电话 / 微信"></label>
          </div>
          <button
            class="yxz-studio-build"
            :disabled="laserBusy || !sessionId"
            @click="generateLaserCard"
          >
            {{ laserBusy ? '生成中…' : '生成切割卡片' }}
          </button>

          <p v-if="laserError" class="yxz-studio-error">
            {{ laserError }}
          </p>

          <div v-if="laserCard" class="yxz-studio-laser">
            <div class="yxz-studio-laser-tabs">
              <button type="button" :class="{ active: laserSide === 'front' }" @click="laserSide = 'front'">
                正面 · 作品
              </button>
              <button type="button" :class="{ active: laserSide === 'back' }" @click="laserSide = 'back'">
                背面 · 活动背景
              </button>
            </div>
            <img :src="laserCardImage" :alt="laserSide === 'front' ? '卡片正面' : '卡片背面'">
            <div class="yxz-studio-laser-links">
              <a :href="laserCard.svgUrl" download rel="noreferrer">下载切割 SVG</a>
              <a :href="laserCard.pngUrl" target="_blank" rel="noopener noreferrer">打开整卡预览</a>
              <button type="button" class="yxz-studio-linkish" @click="openLaserCardInSoftware">
                用 xTool 打开切割
              </button>
            </div>
            <p v-if="laserSoftwareMessage" class="yxz-studio-note">
              {{ laserSoftwareMessage }}
            </p>
          </div>
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.yxz-studio {
  /* The shell hands the page a viewport-sized flex box. Without this the
     page is squeezed into it and the dark background stops halfway down
     while the content keeps going. */
  flex: 0 0 auto;
  min-height: 100vh;
  background:
    radial-gradient(1200px 700px at 30% -10%, rgba(56, 182, 255, .14) 0%, transparent 60%),
    linear-gradient(160deg, #071a30 0%, #0b2a4a 46%, #061527 100%);
  color: #eaf6ff;
  padding: 20px 22px 32px;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}

.yxz-studio-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.yxz-studio-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.yxz-studio-title strong {
  font-size: 20px;
  letter-spacing: .03em;
}

.yxz-studio-title small {
  color: #bcd9f2;
  font-size: 12.5px;
}

.yxz-studio-header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.yxz-studio-header-actions a {
  border: 1px solid rgba(160, 205, 255, .45);
  border-radius: 8px;
  background: rgba(255, 255, 255, .07);
  color: #d9ecff;
  padding: 8px 14px;
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
}

.yxz-studio-header-actions a:hover {
  background: rgba(255, 255, 255, .14);
}

.yxz-studio-open,
.yxz-studio-download {
  border-color: #38b6ff !important;
  background: #1e7fb8 !important;
  color: #fff !important;
}

/* View switcher */
.yxz-studio-views {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.yxz-studio-views button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 18px;
  border: 1px solid rgba(160, 205, 255, .3);
  border-radius: 10px;
  background: rgba(255, 255, 255, .05);
  color: #b9d8f2;
  font-size: 13px;
  cursor: pointer;
  transition: all .2s ease;
}

.yxz-studio-views button:hover:not(:disabled) {
  background: rgba(255, 255, 255, .1);
}

.yxz-studio-views button.active {
  border-color: #38b6ff;
  background: rgba(56, 182, 255, .16);
  color: #fff;
  box-shadow: 0 0 14px rgba(56, 182, 255, .25);
}

.yxz-studio-views button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.yxz-view-icon {
  font-size: 15px;
}

.yxz-view-badge {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(56, 182, 255, .22);
  color: #a9ddff;
  font-size: 10px;
}

.yxz-studio-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  max-width: 1320px;
  margin: 0 auto;
}

.yxz-studio-presets {
  max-width: 1320px;
  margin: 14px auto 0;
  padding: 14px 18px;
  border: 1px solid rgba(96, 165, 250, .32);
  border-radius: 14px;
  background: rgba(13, 37, 66, .55);
}

.yxz-studio-presets-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.yxz-studio-presets-head strong {
  font-size: 15px;
  color: #dff1ff;
}

.yxz-studio-presets-head small {
  color: #8fb8dd;
  font-size: 12px;
}

.yxz-studio-presets-retry {
  padding: 3px 10px;
  border: 1px solid rgba(96, 165, 250, .45);
  border-radius: 6px;
  background: rgba(96, 165, 250, .14);
  color: #cfe6ff;
  font-size: 12px;
  cursor: pointer;
}

.yxz-studio-presets-error {
  margin: 0 0 12px;
  color: #ffb4b4;
  font-size: 12px;
}

.yxz-studio-presets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px;
}

.yxz-studio-preset {
  border: 1px solid rgba(96, 165, 250, .22);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, .04);
  display: flex;
  flex-direction: column;
}

.yxz-studio-preset-thumb {
  position: relative;
  display: block;
  aspect-ratio: 1 / 1;
  background: linear-gradient(160deg, #0d2542, #123a63);
  overflow: hidden;
}

.yxz-studio-preset-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.yxz-studio-preset-ph {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 44px;
}

.yxz-studio-preset-preview {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 6px 0;
  text-align: center;
  font-size: 12px;
  color: #eaf6ff;
  background: rgba(6, 21, 39, .72);
  opacity: 0;
  transition: opacity .2s;
}

.yxz-studio-preset-thumb:hover .yxz-studio-preset-preview {
  opacity: 1;
}

.yxz-studio-preset-body {
  padding: 10px 12px 12px;
}

.yxz-studio-preset-body h4 {
  font-size: 14px;
  color: #e4f3ff;
  margin: 0 0 4px;
}

.yxz-studio-preset-body p {
  font-size: 11.5px;
  color: #93b7d9;
  margin: 0 0 8px;
  line-height: 1.45;
}

.yxz-studio-preset-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.yxz-studio-preset-link {
  font-size: 12px;
  color: #b9e2ff;
  text-decoration: none;
  border: 1px solid rgba(150, 205, 255, .4);
  border-radius: 6px;
  padding: 5px 10px;
  background: rgba(255, 255, 255, .06);
}

.yxz-studio-preset-link:hover {
  background: rgba(255, 255, 255, .12);
}

@media (max-width: 900px) {
  .yxz-studio-main { grid-template-columns: 1fr; }
}

.yxz-studio-canvas {
  min-width: 0;
  min-height: 620px;
  background: rgba(255, 255, 255, .03);
  border: 1px solid rgba(160, 205, 255, .2);
  border-radius: 14px;
  padding: 10px;
}

.yxz-studio-3d {
  min-width: 0;
  min-height: 620px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: rgba(255, 255, 255, .03);
  border: 1px solid rgba(160, 205, 255, .2);
  border-radius: 14px;
  padding: 10px;
}

.yxz-studio-3d-frame {
  flex: 1;
  width: 100%;
  border: 0;
  border-radius: 10px;
  background: #0a1a2c;
}

.yxz-studio-3d-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.yxz-studio-3d-actions a {
  border: 1px solid #38b6ff;
  border-radius: 8px;
  background: #1e7fb8;
  color: #fff;
  padding: 8px 14px;
  font-size: 13px;
  text-decoration: none;
}

.yxz-studio-parts {
  margin-top: 16px;
  border-top: 1px solid #1d4a6b;
  padding-top: 14px;
}

.yxz-studio-parts-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: baseline;
  margin-bottom: 10px;
}

.yxz-studio-parts-head strong {
  color: #d6efff;
  font-size: 15px;
}

.yxz-studio-parts-head small {
  color: #8fb9d6;
  font-size: 12px;
}

.yxz-studio-parts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 10px;
}

.yxz-studio-part {
  border: 1px solid #1d4a6b;
  border-radius: 10px;
  background: #0e3350;
  padding: 10px 12px;
}

.yxz-studio-part h5 {
  margin: 0 0 4px;
  color: #d6efff;
  font-size: 14px;
}

.yxz-studio-part p {
  margin: 0 0 8px;
  color: #8fb9d6;
  font-size: 12px;
}

.yxz-studio-part-actions {
  display: flex;
  gap: 8px;
}

.yxz-studio-3d-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: #7fa9cc;
}

.yxz-studio-3d-empty-icon {
  font-size: 56px;
  opacity: .6;
}

.yxz-studio-3d-empty p {
  font-size: 14px;
}

.yxz-studio-3d-building {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.yxz-studio-3d-building-preview {
  position: relative;
  flex: 1;
  min-height: 260px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(160, 205, 255, .22);
  background: rgba(6, 21, 39, .6);
}

.yxz-studio-3d-building-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: saturate(.85) brightness(.72);
}

.yxz-studio-3d-building-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  text-align: center;
  background: radial-gradient(circle at 50% 45%, rgba(11, 42, 74, .35) 0%, rgba(4, 16, 30, .82) 78%);
}

.yxz-studio-3d-building-overlay strong {
  font-size: 15px;
  color: #eaf6ff;
}

.yxz-studio-3d-building-overlay small {
  font-size: 12px;
  color: #7fa9cc;
}

.yxz-studio-3d-building-spinner {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 3px solid rgba(56, 182, 255, .25);
  border-top-color: #38b6ff;
  animation: yxz-studio-spin 900ms linear infinite;
}

@keyframes yxz-studio-spin {
  to {
    transform: rotate(360deg);
  }
}

.yxz-studio-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.yxz-studio-card {
  background: rgba(255, 255, 255, .05);
  border: 1px solid rgba(160, 205, 255, .22);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.yxz-studio-laser-bg {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(160, 205, 255, .18);
  background: rgba(255, 255, 255, .03);
}

.yxz-studio-laser-bg-label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: #7fa9cc;
}

.yxz-studio-laser-bg-label textarea {
  width: 100%;
  resize: vertical;
  border-radius: 8px;
  border: 1px solid rgba(160, 205, 255, .22);
  background: rgba(6, 21, 39, .7);
  color: #eaf6ff;
  padding: 8px 10px;
  font-size: 12px;
  font-family: inherit;
  line-height: 1.5;
}

.yxz-studio-laser-bg-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.yxz-studio-laser-templates {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.yxz-studio-laser-template {
  flex: none;
  width: 108px;
  border: 1px solid rgba(160, 205, 255, .2);
  border-radius: 8px;
  background: rgba(6, 21, 39, .6);
  color: #9fc6e6;
  font-size: 11px;
  padding: 4px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
}

.yxz-studio-laser-template.active {
  border-color: #38b6ff;
  color: #eaf6ff;
  box-shadow: 0 0 0 1px rgba(56, 182, 255, .5);
}

.yxz-studio-laser-template img {
  width: 100%;
  height: 46px;
  object-fit: cover;
  border-radius: 6px;
  display: block;
}

.yxz-studio-card h3 {
  margin: 0;
  font-size: 14px;
  color: #d9ecff;
}

.yxz-studio-caption {
  margin: 0;
  color: #eaf6ff;
  font-size: 13px;
  line-height: 1.5;
}

.yxz-studio-note {
  margin: 0;
  color: #7fa9cc;
  font-size: 12px;
  line-height: 1.5;
}

.yxz-studio-build {
  border: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, #1e7fb8 0%, #38b6ff 100%);
  color: #fff;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all .2s ease;
}

.yxz-studio-build:hover:not(:disabled) {
  filter: brightness(1.12);
}

.yxz-studio-build:disabled {
  cursor: not-allowed;
  opacity: .6;
}

.yxz-studio-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.yxz-studio-progress-bar {
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, .1);
}

.yxz-studio-progress-bar span {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #1e7fb8, #38b6ff);
  transition: width .4s ease;
}

.yxz-studio-progress p {
  margin: 0;
  color: #a9ddff;
  font-size: 12px;
}

.yxz-studio-stages {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.yxz-studio-stages.is-wide {
  gap: 10px;
}

.yxz-studio-stages li {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  opacity: .45;
  transition: opacity .3s ease;
}

.yxz-studio-stages li.is-done,
.yxz-studio-stages li.is-active,
.yxz-studio-stages li.is-failed {
  opacity: 1;
}

.yxz-studio-stage-dot {
  flex: none;
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 50%;
  background: rgba(255, 255, 255, .28);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, .06);
}

.yxz-studio-stages li.is-done .yxz-studio-stage-dot {
  background: #7ff2a8;
  box-shadow: 0 0 0 3px rgba(127, 242, 168, .18);
}

.yxz-studio-stages li.is-active .yxz-studio-stage-dot {
  background: #38b6ff;
  box-shadow: 0 0 0 4px rgba(56, 182, 255, .2);
  animation: yxz-studio-pulse 1.4s ease-in-out infinite;
}

.yxz-studio-stages li.is-failed .yxz-studio-stage-dot {
  background: #ff8f8f;
  box-shadow: 0 0 0 4px rgba(255, 143, 143, .2);
}

@keyframes yxz-studio-pulse {
  50% {
    box-shadow: 0 0 0 7px rgba(56, 182, 255, 0);
  }
}

.yxz-studio-stages li strong {
  display: block;
  font-size: 12px;
  color: #eaf6ff;
  font-weight: 600;
}

.yxz-studio-stages li small {
  display: block;
  font-size: 11px;
  color: #7fa9cc;
  line-height: 1.5;
}

.yxz-studio-elapsed {
  margin: 0;
  color: #7fa9cc;
  font-size: 11px;
}

.yxz-studio-error {
  margin: 0;
  color: #ff8f8f;
  font-size: 12px;
}

.yxz-studio-done {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #7ff2a8;
  font-size: 13px;
}

.yxz-studio-done a {
  color: #8fd4ff;
  text-decoration: none;
  font-size: 12px;
}

.yxz-studio-linkish {
  border: 0;
  background: transparent;
  color: #8fd4ff;
  font-size: 12px;
  text-align: left;
  padding: 0;
  cursor: pointer;
  text-decoration: underline;
}

.yxz-studio-laser-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 8px 0;
}

.yxz-studio-laser-fields label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #9fc4dd;
  font-size: 11px;
}

.yxz-studio-laser-fields input {
  border: 1px solid rgba(143, 212, 255, .28);
  border-radius: 8px;
  padding: 6px 8px;
  background: rgba(10, 26, 44, .7);
  color: #dff0ff;
  font-size: 12px;
}

.yxz-studio-laser {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}

.yxz-studio-laser-tabs {
  display: flex;
  gap: 6px;
}

.yxz-studio-laser-tabs button {
  flex: 1;
  border: 1px solid rgba(143, 212, 255, .28);
  border-radius: 8px;
  background: rgba(10, 26, 44, .7);
  color: #9fc4dd;
  padding: 5px 6px;
  font-size: 11px;
  cursor: pointer;
}

.yxz-studio-laser-tabs button.active {
  border-color: #4db8f0;
  color: #dff0ff;
}

.yxz-studio-laser img {
  display: block;
  width: 100%;
  border: 1px solid rgba(143, 212, 255, .25);
  border-radius: 10px;
  background: #fff;
}

.yxz-studio-laser-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.yxz-studio-laser-links a {
  color: #8fd4ff;
  font-size: 12px;
  text-decoration: underline;
}
</style>
