<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import YXZPreviewCanvasEditor from '../../../../packages/stage-ui/src/components/scenes/YXZPreviewCanvasEditor.vue'
import { createYXZCartoonModel, type YXZModelProgress } from '../../../../packages/stage-ui/src/composables/use-yxz-print-preview'

const route = useRoute()
const sessionId = String(route.query.session ?? '')
const imageIndex = Number(route.query.image ?? 0)
const previewSrc = String(route.query.src ?? '')
const caption = String(route.query.caption ?? '宜小智创作方案')

const editedDataUrl = ref('')
const building = ref(false)
const progress = ref<YXZModelProgress | null>(null)
const model = ref<{ glbUrl: string, stlUrl: string } | null>(null)
const errorMessage = ref('')
// '2d' = canvas editing, '3d' = model preview (scene switching like Tripo)
const activeView = ref<'2d' | '3d'>('2d')

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
      onProgress: p => {
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
          <div class="yxz-studio-3d-empty-icon">🧊</div>
          <p>先在 2D 画布完成编辑，再点击「生成 3D 模型」</p>
          <button type="button" class="yxz-studio-build" @click="activeView = '2d'">返回 2D 编辑</button>
        </div>
      </section>

      <!-- Right control panel -->
      <aside class="yxz-studio-side">
        <div class="yxz-studio-card">
          <h3>当前方案</h3>
          <p class="yxz-studio-caption">{{ caption }}</p>
          <p v-if="editedDataUrl" class="yxz-studio-note">✓ 已应用你的批注编辑，将随模型一起生成</p>
        </div>

        <div class="yxz-studio-card">
          <h3>生成彩色 3D 模型</h3>
          <p class="yxz-studio-note">引擎优先 Tripo3D 高清（PBR 彩色）→ 混元3D 云端 → 本地彩色，自动切换。</p>
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

          <p v-if="errorMessage" class="yxz-studio-error">{{ errorMessage }}</p>

          <div v-if="model" class="yxz-studio-done">
            <span>✓ 模型已完成</span>
            <button type="button" class="yxz-studio-linkish" @click="switchView('3d')">切换到 3D 预览</button>
            <a :href="`${model.stlUrl}${model.stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL（打印用）</a>
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
</style>
