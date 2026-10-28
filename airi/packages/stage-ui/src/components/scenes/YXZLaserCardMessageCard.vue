<script setup lang="ts">
import type { YXZLocalSoftware } from '../../composables/use-yxz-print-preview'

import { computed, ref } from 'vue'

import { detectYXZLocalSoftware, openYXZLaserCardInSoftware } from '../../composables/use-yxz-print-preview'

const props = withDefaults(defineProps<{
  sessionId: string
  svgUrl: string
  pngUrl: string
  frontUrl: string
  backUrl: string
  sizeMm: { width: number, height: number }
  backTemplate?: string
  artworkSessionId?: string
  artworkImageIndex?: number
  name?: string
  description?: string
  hasArtwork?: boolean
}>(), {
  backTemplate: 'activity_stage',
  artworkImageIndex: 0,
  name: '',
  description: '',
  hasArtwork: false,
})

const laserTool = ref<YXZLocalSoftware | null>(null)
const toolMessage = ref('')
const toolBusy = ref(false)

const sizeLabel = computed(() => `${props.sizeMm.width} × ${props.sizeMm.height} mm`)
const aspectRatio = computed(() => {
  const width = props.sizeMm.width || 100
  const height = props.sizeMm.height || 56.25
  return `${width} / ${height}`
})

async function ensureLaserTool() {
  if (laserTool.value)
    return laserTool.value

  const tools = await detectYXZLocalSoftware()
  laserTool.value = tools.find(tool => tool.kind === 'laser') ?? null
  return laserTool.value
}

async function openInLaserSoftware() {
  if (toolBusy.value)
    return

  toolBusy.value = true
  toolMessage.value = ''
  try {
    const tool = await ensureLaserTool()
    if (!tool) {
      toolMessage.value = '未检测到 xTool / 激光切割软件，可先下载 SVG 再手动导入。'
      return
    }
    if (!tool.available) {
      toolMessage.value = `未检测到 ${tool.name || '激光软件'}，可先下载 SVG 再手动导入。`
      return
    }
    await openYXZLaserCardInSoftware(tool.id, props.sessionId)
    toolMessage.value = `已在 ${tool.name || '激光软件'} 中打开切割文件，请在该软件里确认尺寸与切割参数。`
  }
  catch (error) {
    toolMessage.value = error instanceof Error ? error.message : '打开激光软件失败'
  }
  finally {
    toolBusy.value = false
  }
}

function openStudio() {
  if (!props.artworkSessionId || typeof window === 'undefined')
    return

  const url = new URL('/yxz-studio', window.location.origin)
  url.searchParams.set('session', props.artworkSessionId)
  url.searchParams.set('image', String(props.artworkImageIndex ?? 0))
  url.searchParams.set('src', props.frontUrl)
  url.searchParams.set('caption', props.name || '宜小智激光切剪卡片')
  window.open(url.toString(), '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <article class="yxz-laser-card" aria-label="宜小智激光切剪卡片">
    <div class="yxz-laser-card-heading">
      <div>
        <span class="yxz-laser-card-eyebrow">激光切剪作品卡</span>
        <strong>{{ name || '我的切剪卡片' }}</strong>
      </div>
      <span class="yxz-laser-card-size">{{ sizeLabel }}</span>
    </div>

    <!-- Front on top, back underneath: one glance shows the whole card. -->
    <figure class="yxz-laser-card-face">
      <figcaption>正面 · 你的作品</figcaption>
      <div class="yxz-laser-card-preview" :style="{ aspectRatio }">
        <img :src="frontUrl" alt="卡片正面" loading="lazy">
      </div>
    </figure>

    <figure class="yxz-laser-card-face">
      <figcaption>背面 · 活动主题</figcaption>
      <div class="yxz-laser-card-preview" :style="{ aspectRatio }">
        <img :src="backUrl" alt="卡片背面" loading="lazy">
      </div>
    </figure>

    <p v-if="description" class="yxz-laser-card-description">
      {{ description }}
    </p>
    <p class="yxz-laser-card-note">
      尺寸 {{ sizeLabel }}，正面是你的作品图与个人信息，背面是活动主题主视觉；SVG 已内嵌正反两面，可直接交给 xTool 切割。
    </p>

    <div class="yxz-laser-card-actions">
      <a :href="svgUrl" download rel="noreferrer">下载切割 SVG</a>
      <a :href="pngUrl" target="_blank" rel="noopener noreferrer">打开正反面预览</a>
      <button type="button" :disabled="toolBusy" @click="openInLaserSoftware">
        {{ toolBusy ? '打开中…' : '用 xTool 打开切割' }}
      </button>
      <button v-if="artworkSessionId" type="button" class="is-primary" @click="openStudio">
        打开创作面板
      </button>
    </div>

    <p v-if="toolMessage" class="yxz-laser-card-tool-message">
      {{ toolMessage }}
    </p>
  </article>
</template>

<style scoped>
.yxz-laser-card {
  display: flex;
  flex-direction: column;
  gap: .55rem;
  margin-top: .75rem;
  padding: .7rem .8rem;
  border: 1px solid #b5dce9;
  border-radius: .8rem;
  background: rgba(240, 248, 252, .92);
  color: #234b61;
}

.yxz-laser-card-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: .6rem;
}

.yxz-laser-card-eyebrow {
  display: block;
  color: #6b8798;
  font-size: .68rem;
  letter-spacing: .04em;
}

.yxz-laser-card-heading strong {
  font-size: .95rem;
  color: #15547c;
}

.yxz-laser-card-size {
  flex: none;
  border: 1px solid #18a8e0;
  border-radius: .45rem;
  padding: .15rem .45rem;
  color: #087eae;
  font-size: .68rem;
}

.yxz-laser-card-face {
  margin: 0;
}

.yxz-laser-card-face figcaption {
  margin-bottom: .25rem;
  color: #15547c;
  font-size: .74rem;
  font-weight: 600;
}

.yxz-laser-card-preview {
  overflow: hidden;
  border: 1px solid #b5dce9;
  border-radius: .6rem;
  background: #fff;
}

.yxz-laser-card-preview img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.yxz-laser-card-description,
.yxz-laser-card-note {
  margin: 0;
  color: #52758a;
  font-size: .72rem;
  line-height: 1.5;
}

.yxz-laser-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  align-items: center;
}

.yxz-laser-card-actions a,
.yxz-laser-card-actions button {
  border: 1px solid #b5dce9;
  border-radius: .45rem;
  background: #fff;
  color: #087eae;
  padding: .32rem .55rem;
  cursor: pointer;
  font-size: .7rem;
  text-decoration: none;
}

.yxz-laser-card-actions button.is-primary {
  border-color: #18a8e0;
  background: #18a8e0;
  color: #fff;
  font-weight: 600;
}

.yxz-laser-card-actions button:disabled {
  cursor: wait;
  opacity: .6;
}

.yxz-laser-card-tool-message {
  margin: 0;
  color: #087eae;
  font-size: .68rem;
  line-height: 1.5;
}
</style>
