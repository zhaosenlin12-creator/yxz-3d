<script setup lang="ts">
import { computed, ref } from 'vue'

import { yxzPreviewPageUrl } from '../../composables/use-yxz-print-preview'

export interface YXZCardPreviewItem {
  src: string
  caption: string
}

const props = withDefaults(defineProps<{
  previewSrc: string
  caption: string
  description?: string
  modelUrl?: string
  stlUrl?: string
  sessionId?: string
  interactive?: boolean
  status?: 'preview' | 'model-building' | 'model-ready'
  progressMsg?: string
  previews?: YXZCardPreviewItem[]
}>(), {
  description: '',
  interactive: true,
  status: 'preview',
  progressMsg: '',
  previews: () => [],
})

const emit = defineEmits<{
  (event: 'adopt'): void
  (event: 'redescribe'): void
}>()
const copied = ref(false)
const modelPreviewUrl = computed(() => props.modelUrl ? yxzPreviewPageUrl(props.modelUrl) : '')

const gallery = computed<YXZCardPreviewItem[]>(() => {
  const items = props.previews?.length ? props.previews : [{ src: props.previewSrc, caption: props.caption }]
  return items.filter(item => item.src)
})
const lightboxOpen = ref(false)
const lightboxIndex = ref(0)

function openStudio() {
  const item = gallery.value[lightboxIndex.value]
  if (!item || !props.sessionId)
    return
  const index = (props.previews?.length ? props.previews?.findIndex(p => p.src === item.src) : 0) ?? 0
  const url = new URL('/yxz-studio', typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:5199')
  url.searchParams.set('session', props.sessionId)
  url.searchParams.set('image', String(Math.max(0, index)))
  url.searchParams.set('src', item.src)
  url.searchParams.set('caption', item.caption || props.caption)
  window.open(url.toString(), '_blank', 'noopener,noreferrer')
}

function openLightbox(index: number) {
  lightboxIndex.value = index
  lightboxOpen.value = true
}

function closeLightbox() {
  lightboxOpen.value = false
}

function stepLightbox(delta: number) {
  if (!gallery.value.length)
    return
  lightboxIndex.value = (lightboxIndex.value + delta + gallery.value.length) % gallery.value.length
}

function openLightboxInNewTab() {
  const item = gallery.value[lightboxIndex.value]
  if (!item)
    return
  window.open(item.src, '_blank', 'noopener,noreferrer')
}

const badgeText = computed(() => {
  if (props.status === 'model-ready')
    return '模型已完成'
  if (props.status === 'model-building')
    return '制作中…'
  return '可继续制作'
})

async function copyPreviewAddress() {
  if (!modelPreviewUrl.value)
    return
  try {
    await navigator.clipboard.writeText(modelPreviewUrl.value)
    copied.value = true
    window.setTimeout(() => copied.value = false, 1600)
  }
  catch {
    copied.value = false
  }
}
</script>

<template>
  <article class="yxz-creation-card" aria-label="宜小智创作方案">
    <div class="yxz-creation-card-heading">
      <div>
        <span class="yxz-creation-card-eyebrow">宜小智创作方案</span>
        <strong>{{ caption }}</strong>
      </div>
      <span class="yxz-creation-card-badge" :class="`is-${status}`">{{ badgeText }}</span>
    </div>
    <div v-if="status === 'model-building'" class="yxz-creation-card-building">
      <span class="yxz-creation-card-building-dot" />
      <span>{{ progressMsg || '正在制作 3D 模型，请耐心等待…' }}</span>
    </div>
    <img
      :src="previewSrc"
      :alt="caption"
      class="yxz-creation-card-image"
      :class="{ 'is-blurred': status === 'model-building' }"
      role="button"
      tabindex="0"
      @click="openLightbox(0)"
      @keydown.enter="openLightbox(0)"
    >
    <div class="yxz-creation-card-zoom-hint">
      <button type="button" @click="openLightbox(0)">点击放大预览</button>
      <a :href="previewSrc" target="_blank" rel="noopener noreferrer">在新页面打开</a>
      <button v-if="sessionId && status !== 'model-building'" type="button" class="yxz-creation-card-studio" @click="openStudio">打开创作面板</button>
      <span v-if="gallery.length > 1">共 {{ gallery.length }} 张</span>
    </div>
    <p v-if="description" class="yxz-creation-card-description">{{ description }}</p>
    <div v-if="interactive && status !== 'model-building'" class="yxz-creation-card-actions">
      <button type="button" class="yxz-creation-card-primary" @click="emit('adopt')">采用这个方案</button>
      <button type="button" class="yxz-creation-card-secondary" @click="emit('redescribe')">重新描述</button>
    </div>
    <div v-if="modelUrl || stlUrl" class="yxz-creation-card-links">
      <a v-if="modelUrl" :href="modelPreviewUrl" target="_blank" rel="noopener noreferrer">打开 3D 预览</a>
      <a v-if="stlUrl" :href="`${stlUrl}${stlUrl.includes('?') ? '&' : '?'}download=1`" download rel="noreferrer">下载 STL</a>
    </div>
    <div v-if="modelUrl" class="yxz-creation-card-address">
      <span>预览地址：{{ modelPreviewUrl }}</span>
      <button type="button" @click="copyPreviewAddress">{{ copied ? '已复制' : '复制地址' }}</button>
    </div>

    <Teleport to="body">
      <div v-if="lightboxOpen" class="yxz-lightbox" role="dialog" aria-modal="true" @click.self="closeLightbox">
        <div class="yxz-lightbox-topbar">
          <span>{{ gallery[lightboxIndex]?.caption || '' }}</span>
          <div class="yxz-lightbox-topbar-actions">
            <button type="button" @click="openLightboxInNewTab">新页面打开</button>
            <button type="button" @click="closeLightbox">关闭 ✕</button>
          </div>
        </div>
        <div class="yxz-lightbox-stage">
          <button v-if="gallery.length > 1" type="button" class="yxz-lightbox-nav is-prev" aria-label="上一张" @click="stepLightbox(-1)">‹</button>
          <img :src="gallery[lightboxIndex]?.src" :alt="gallery[lightboxIndex]?.caption || '预览'" class="yxz-lightbox-image">
          <button v-if="gallery.length > 1" type="button" class="yxz-lightbox-nav is-next" aria-label="下一张" @click="stepLightbox(1)">›</button>
        </div>
        <div v-if="gallery.length > 1" class="yxz-lightbox-thumbs">
          <button
            v-for="(item, index) in gallery"
            :key="`${item.src}-${index}`"
            type="button"
            class="yxz-lightbox-thumb"
            :class="{ 'is-active': index === lightboxIndex }"
            @click="lightboxIndex = index"
          >
            <img :src="item.src" :alt="item.caption">
          </button>
        </div>
      </div>
    </Teleport>
  </article>
</template>

<style scoped>
.yxz-creation-card {
  display: flex;
  flex-direction: column;
  gap: .65rem;
  padding: .85rem;
  border: 1px solid color-mix(in srgb, #18a8e0 32%, transparent);
  border-radius: 1rem;
  background: linear-gradient(145deg, rgba(255, 255, 255, .96), rgba(232, 248, 255, .86));
  box-shadow: 0 12px 30px rgba(25, 110, 150, .12);
}

.yxz-creation-card-heading,
.yxz-creation-card-actions,
.yxz-creation-card-links {
  display: flex;
  gap: .55rem;
  align-items: center;
  justify-content: space-between;
}

.yxz-creation-card-heading > div {
  display: flex;
  flex-direction: column;
  gap: .15rem;
}

.yxz-creation-card-eyebrow {
  color: #087eae;
  font-size: .68rem;
  letter-spacing: .04em;
}

.yxz-creation-card-heading strong {
  color: #15547c;
  font-size: .9rem;
}

.yxz-creation-card-badge {
  flex: none;
  padding: .25rem .45rem;
  border-radius: 999px;
  background: rgba(24, 168, 224, .12);
  color: #087eae;
  font-size: .68rem;
}

.yxz-creation-card-image {
  display: block;
  width: 100%;
  max-height: 15rem;
  border-radius: .7rem;
  object-fit: cover;
}

.yxz-creation-card-description {
  margin: 0;
  color: #52758a;
  font-size: .76rem;
  line-height: 1.5;
}

.yxz-creation-card-actions button {
  flex: 1;
  min-height: 2.25rem;
  border-radius: .65rem;
  cursor: pointer;
  font-size: .76rem;
}

.yxz-creation-card-primary {
  border: 0;
  background: #18a8e0;
  color: #fff;
}

.yxz-creation-card-secondary {
  border: 1px solid #b5dce9;
  background: rgba(255, 255, 255, .72);
  color: #15547c;
}

.yxz-creation-card-links {
  justify-content: flex-start;
  font-size: .73rem;
}

.yxz-creation-card-links a {
  color: #087eae;
  text-decoration: underline;
}

.yxz-creation-card-address {
  display: flex;
  gap: .45rem;
  align-items: center;
  color: #6b8798;
  font-size: .65rem;
}

.yxz-creation-card-address span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.yxz-creation-card-address button {
  flex: none;
  border: 1px solid #b5dce9;
  border-radius: .4rem;
  background: #fff;
  color: #087eae;
  padding: .2rem .35rem;
  cursor: pointer;
  font-size: .65rem;
}

.yxz-creation-card-building {
  display: flex;
  gap: .45rem;
  align-items: center;
  padding: .5rem .6rem;
  border-radius: .6rem;
  background: rgba(24, 168, 224, .1);
  color: #087eae;
  font-size: .76rem;
}

.yxz-creation-card-building-dot {
  width: .55rem;
  height: .55rem;
  flex: none;
  border-radius: 999px;
  background: #18a8e0;
  animation: yxz-pulse 1.1s ease-in-out infinite;
}

@keyframes yxz-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .35; transform: scale(.72); }
}

.yxz-creation-card-image.is-blurred {
  filter: blur(3px) saturate(.9);
  opacity: .75;
}

.yxz-creation-card-zoom-hint {
  display: flex;
  gap: .8rem;
  align-items: center;
  font-size: .7rem;
  color: #6b8798;
}

.yxz-creation-card-zoom-hint button,
.yxz-creation-card-zoom-hint a {
  border: 0;
  background: none;
  padding: 0;
  color: #087eae;
  cursor: pointer;
  font-size: .7rem;
  text-decoration: underline;
}

.yxz-creation-card-zoom-hint .yxz-creation-card-studio {
  margin-left: .2rem;
  padding: .18rem .4rem;
  border: 1px solid #18a8e0;
  border-radius: .45rem;
  background: rgba(24, 168, 224, .08);
  color: #087eae;
  text-decoration: none;
  font-weight: 600;
}

.yxz-creation-card-zoom-hint .yxz-creation-card-studio:hover {
  background: rgba(24, 168, 224, .16);
}

.yxz-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  background: rgba(4, 14, 30, .92);
}

.yxz-lightbox-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: .7rem 1rem;
  color: #d9ecff;
  font-size: .85rem;
}

.yxz-lightbox-topbar-actions {
  display: flex;
  gap: .6rem;
}

.yxz-lightbox-topbar-actions button {
  border: 1px solid rgba(160, 205, 255, .5);
  border-radius: .5rem;
  background: rgba(255, 255, 255, .08);
  color: #d9ecff;
  padding: .3rem .7rem;
  cursor: pointer;
  font-size: .75rem;
}

.yxz-lightbox-stage {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  padding: 0 4.5rem;
}

.yxz-lightbox-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: .5rem;
  box-shadow: 0 18px 60px rgba(0, 0, 0, .5);
}

.yxz-lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 2.6rem;
  height: 2.6rem;
  border: 1px solid rgba(160, 205, 255, .4);
  border-radius: 999px;
  background: rgba(255, 255, 255, .08);
  color: #fff;
  font-size: 1.6rem;
  cursor: pointer;
  line-height: 1;
}

.yxz-lightbox-nav.is-prev { left: 1rem; }
.yxz-lightbox-nav.is-next { right: 1rem; }

.yxz-lightbox-thumbs {
  display: flex;
  gap: .5rem;
  justify-content: center;
  padding: .8rem 1rem 1.2rem;
}

.yxz-lightbox-thumb {
  width: 4.2rem;
  height: 3rem;
  overflow: hidden;
  border: 2px solid transparent;
  border-radius: .45rem;
  background: none;
  padding: 0;
  cursor: pointer;
  opacity: .6;
}

.yxz-lightbox-thumb.is-active {
  border-color: #4db8f0;
  opacity: 1;
}

.yxz-lightbox-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
