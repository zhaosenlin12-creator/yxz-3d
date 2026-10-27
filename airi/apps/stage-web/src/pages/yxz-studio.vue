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

function onSave(dataUrl: string) {
  editedDataUrl.value = dataUrl
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
        <strong>宜小智 · 创作面板</strong>
        <small>在预览上自由编辑（画笔 / 箭头 / 图形 / 文字），满意后一键生成彩色 3D 模型</small>
      </div>
      <div class="yxz-studio-header-actions">
        <a class="yxz-studio-back" :href="origin" @click.prevent="goBack">返回对话</a>
        <a v-if="model" class="yxz-studio-open" :href="modelPreviewUrl" target="_blank" rel="noopener noreferrer">打开 3D 预览 ↗</a>
        <a v-if="model" class="yxz-studio-download" :href="`${model.stlUrl}${model.stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL</a>
      </div>
    </header>

    <main class="yxz-studio-main">
      <section class="yxz-studio-canvas">
        <YXZPreviewCanvasEditor
          :image-src="previewSrc"
          :caption="caption"
          @save="onSave"
        />
      </section>

      <aside class="yxz-studio-side">
        <div class="yxz-studio-card">
          <h3>当前方案</h3>
          <p class="yxz-studio-caption">{{ caption }}</p>
          <p v-if="editedDataUrl" class="yxz-studio-note">✓ 已应用你的批注编辑，将随模型一起生成</p>
        </div>

        <div class="yxz-studio-card">
          <h3>生成彩色 3D 模型</h3>
          <p class="yxz-studio-note">引擎优先 Tripo3D 高清（PBR 彩色），不可用时自动切换本地彩色引擎。</p>
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
            <a :href="modelPreviewUrl" target="_blank" rel="noopener noreferrer">打开 3D 预览</a>
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
  background: linear-gradient(160deg, #0b2a4a 0%, #123f6b 46%, #0d3054 100%);
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
  margin-bottom: 18px;
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

.yxz-studio-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 18px;
  max-width: 1280px;
  margin: 0 auto;
}

@media (max-width: 860px) {
  .yxz-studio-main { grid-template-columns: 1fr; }
}

.yxz-studio-canvas {
  min-width: 0;
  background: rgba(255, 255, 255, .04);
  border: 1px solid rgba(160, 205, 255, .25);
  border-radius: 14px;
  padding: 16px;
}

.yxz-studio-canvas :deep(.yxz-canvas-editor) {
  margin-top: 0;
  background: #f7fcff;
}

.yxz-studio-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.yxz-studio-card {
  background: rgba(255, 255, 255, .05);
  border: 1px solid rgba(160, 205, 255, .25);
  border-radius: 14px;
  padding: 16px;
}

.yxz-studio-card h3 {
  color: #8fd4ff;
  font-size: 14px;
  margin: 0 0 8px;
}

.yxz-studio-caption {
  margin: 0 0 6px;
  font-size: 13px;
  color: #eaf6ff;
}

.yxz-studio-note {
  margin: 0;
  font-size: 12px;
  color: #bcd9f2;
  line-height: 1.6;
}

.yxz-studio-build {
  width: 100%;
  margin-top: 12px;
  border: 0;
  border-radius: 9px;
  background: linear-gradient(135deg, #38b6ff, #1e7fb8);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  padding: 12px 14px;
  cursor: pointer;
}

.yxz-studio-build:disabled {
  opacity: .55;
  cursor: not-allowed;
}

.yxz-studio-progress {
  margin-top: 12px;
}

.yxz-studio-progress-bar {
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, .12);
  overflow: hidden;
}

.yxz-studio-progress-bar span {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38b6ff, #7fe0ff);
  transition: width .4s ease;
}

.yxz-studio-progress p {
  margin: 6px 0 0;
  font-size: 12px;
  color: #bcd9f2;
}

.yxz-studio-error {
  margin: 10px 0 0;
  color: #ffb3a7;
  font-size: 12.5px;
}

.yxz-studio-done {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(160, 205, 255, .25);
}

.yxz-studio-done span {
  color: #7fe0a8;
  font-size: 13px;
}

.yxz-studio-done a {
  color: #8fd4ff;
  font-size: 13px;
  text-decoration: underline;
}
</style>
