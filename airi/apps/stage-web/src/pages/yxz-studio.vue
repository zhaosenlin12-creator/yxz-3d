<script setup lang="ts">
import type { YXZLaserCardResponse, YXZModelProgress } from '../../../../packages/stage-ui/src/composables/use-yxz-print-preview'

import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import YXZPreviewCanvasEditor from '../../../../packages/stage-ui/src/components/scenes/YXZPreviewCanvasEditor.vue'

import { createYXZCartoonModel, createYXZLaserCard, detectYXZLocalSoftware, getYXZPrintApiBase, openYXZLaserCardInSoftware } from '../../../../packages/stage-ui/src/composables/use-yxz-print-preview'

const route = useRoute()
const sessionId = String(route.query.session ?? '')
const imageIndex = Number(route.query.image ?? 0)
const previewSrc = String(route.query.src ?? '')
const caption = String(route.query.caption ?? '宜小智创作方案')

interface YXZPresetModel {
  id: string
  name: string
  desc: string
  thumbUrl: string | null
  glbUrl: string
  stlUrl: string | null
}

const editedDataUrl = ref('')
const building = ref(false)
const progress = ref<YXZModelProgress | null>(null)
const model = ref<{ glbUrl: string, stlUrl: string } | null>(null)
const errorMessage = ref('')
const presets = ref<YXZPresetModel[]>([])
const presetsLoading = ref(true)
const presetsError = ref('')
// '2d' = canvas editing, '3d' = model preview (scene switching like Tripo)
const activeView = ref<'2d' | '3d'>('2d')

// --- Laser-cut card export -------------------------------------------
// The card is the physical end of the chain: its back is the fixed activity
// artwork and its front is the visitor's own model preview.
const laserForm = ref({ name: '', title: '', unit: '', contact: '' })
const laserCard = ref<YXZLaserCardResponse | null>(null)
const laserBusy = ref(false)
const laserError = ref('')
const laserSide = ref<'front' | 'back'>('front')
const laserSoftwareMessage = ref('')
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
    }
    progress.value = { percent: 100, message: '已载入本方案此前生成的 3D 模型', step: 'done' }
  }
  catch { /* the model simply does not exist yet */ }
}

onMounted(() => {
  void loadPresets()
  void loadExistingModel()
})

function presetPreviewUrl(p: YXZPresetModel) {
  return `/yxz-preview?model=${encodeURIComponent(`${getYXZPrintApiBase()}${p.glbUrl}`)}`
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
  progress.value = { percent: 2, message: '开始制作 3D 模型，请耐心等待…', step: 'building' }
  try {
    const result = await createYXZCartoonModel({
      sessionId,
      imageIndex,
      ...(editedDataUrl.value ? { customImage: editedDataUrl.value } : {}),
      onProgress: (p) => {
        progress.value = p
      },
    })
    model.value = { glbUrl: result.glbUrl, stlUrl: result.stlUrl }
    progress.value = { percent: 100, message: `3D 模型已生成（${result.engine ?? 'Tripo3D'}）`, step: 'done' }
    activeView.value = '3d'
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '3D 生成失败，请重试'
  }
  finally {
    building.value = false
  }
}

const modelPreviewUrl = computed(() => model.value ? `/yxz-preview?model=${encodeURIComponent(model.value.glbUrl)}` : '')
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
        </template>
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
          <h3>生成彩色 3D 模型</h3>
          <p class="yxz-studio-note">
            引擎优先 Tripo3D 高清（PBR 彩色）→ 混元3D 云端 → 本地彩色，自动切换。
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
