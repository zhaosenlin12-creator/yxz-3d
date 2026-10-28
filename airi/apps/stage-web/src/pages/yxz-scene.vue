<script setup lang="ts">
import { computed, ref } from 'vue'

import { getYXZPrintApiBase } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'

const ACCEPTED = '.ply,.splat,.sog,.spz'

const file = ref<File | null>(null)
const busy = ref(false)
const errorMessage = ref('')
const result = ref<{ name: string, size: number, viewerUrl: string, assetUrl: string } | null>(null)
const dragging = ref(false)

const viewerSrc = computed(() => {
  if (!result.value)
    return ''
  // The SuperSplat viewer is served by the 宜小智 backend, together with
  // the scene file it has to read.
  return `${getYXZPrintApiBase()}${result.value.viewerUrl}`
})

function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  const chosen = input.files?.[0]
  if (chosen)
    selectFile(chosen)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  const dropped = event.dataTransfer?.files?.[0]
  if (dropped)
    selectFile(dropped)
}

function selectFile(chosen: File) {
  errorMessage.value = ''
  result.value = null
  const lower = chosen.name.toLowerCase()
  if (!/\.(ply|splat|sog|spz)$/.test(lower)) {
    errorMessage.value = '只支持 .ply / .splat / .sog / .spz 格式的场景成果'
    return
  }
  file.value = chosen
}

async function upload() {
  if (!file.value || busy.value)
    return
  busy.value = true
  errorMessage.value = ''
  try {
    const body = new FormData()
    body.append('asset', file.value)
    body.append('title', file.value.name.replace(/\.[^.]+$/, ''))
    const response = await fetch(`${getYXZPrintApiBase()}/api/scenes/import`, {
      method: 'POST',
      body,
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(text.slice(0, 200) || `上传失败（HTTP ${response.status}）`)
    }
    const payload = await response.json()
    const scene = payload?.result
    if (!scene?.viewerUrl)
      throw new Error('后端没有返回可用的场景预览地址')
    result.value = {
      name: scene.name || file.value.name,
      size: Number(scene.size) || file.value.size,
      viewerUrl: scene.viewerUrl,
      assetUrl: scene.assetUrl || '',
    }
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '上传失败，请重试'
  }
  finally {
    busy.value = false
  }
}

function formatSize(bytes: number) {
  if (bytes > 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes > 1024)
    return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}
</script>

<template>
  <main class="yxz-scene-page">
    <header class="yxz-scene-header">
      <div>
        <span>宜小智</span>
        <strong>真实场景 · 高斯泼溅</strong>
      </div>
      <RouterLink to="/yxz-studio">← 返回创作工作室</RouterLink>
    </header>

    <section class="yxz-scene-panel">
      <p class="yxz-scene-lead">
        载入由 GraphDECO / gsplat 训练出来的真实场景成果，在浏览器里自由走一圈看看。
        支持 .ply、.splat、.sog、.spz 四种格式。
      </p>

      <label
        class="yxz-scene-drop"
        :class="{ 'is-dragging': dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input type="file" :accept="ACCEPTED" @change="pickFile">
        <strong>{{ file ? file.name : '把场景成果拖到这里，或点击选择文件' }}</strong>
        <small v-if="file">{{ formatSize(file.size) }}</small>
        <small v-else>也可以直接在文件管理器里把成果拖进来</small>
      </label>

      <div class="yxz-scene-actions">
        <button type="button" :disabled="!file || busy" @click="upload">
          {{ busy ? '正在载入…' : '载入场景' }}
        </button>
        <a v-if="result?.assetUrl" :href="`${getYXZPrintApiBase()}${result.assetUrl}`" download>
          下载原始成果
        </a>
      </div>

      <p v-if="errorMessage" class="yxz-scene-error">
        {{ errorMessage }}
      </p>
    </section>

    <section v-if="result" class="yxz-scene-viewer">
      <iframe :src="viewerSrc" title="宜小智真实场景预览" />
    </section>
  </main>
</template>

<style scoped>
.yxz-scene-page {
  min-height: 100dvh;
  padding: 1.2rem;
  background: linear-gradient(150deg, #f5fcff, #e5f7fd);
  color: #15547c;
}

.yxz-scene-header {
  display: flex;
  max-width: 72rem;
  margin: 0 auto 1rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.yxz-scene-header div { display: flex; flex-direction: column; gap: .2rem; }
.yxz-scene-header span { color: #087eae; font-size: .78rem; }
.yxz-scene-header strong { font-size: 1.25rem; }
.yxz-scene-header a { color: #087eae; text-decoration: underline; }

.yxz-scene-panel {
  max-width: 72rem;
  margin: 0 auto;
  border: 1px solid #b5dce9;
  border-radius: 1.2rem;
  background: #fff;
  padding: 1.2rem 1.4rem 1.4rem;
  box-shadow: 0 12px 34px rgba(25, 110, 150, .1);
}

.yxz-scene-lead {
  margin: 0 0 1rem;
  color: #3d6b86;
  font-size: .92rem;
  line-height: 1.6;
}

.yxz-scene-drop {
  display: flex;
  flex-direction: column;
  gap: .35rem;
  align-items: center;
  justify-content: center;
  min-height: 8.5rem;
  border: 2px dashed #8fcde6;
  border-radius: 1rem;
  background: #f3fbfe;
  padding: 1.4rem;
  cursor: pointer;
  text-align: center;
}

.yxz-scene-drop.is-dragging { border-color: #087eae; background: #e4f6fd; }
.yxz-scene-drop input { display: none; }
.yxz-scene-drop strong { font-size: 1rem; }
.yxz-scene-drop small { color: #6b8798; font-size: .82rem; }

.yxz-scene-actions {
  display: flex;
  gap: .8rem;
  align-items: center;
  margin-top: .9rem;
}

.yxz-scene-actions button {
  border: 0;
  border-radius: 8px;
  background: #087eae;
  color: #fff;
  padding: .6rem 1.2rem;
  font-size: .9rem;
  cursor: pointer;
}

.yxz-scene-actions button:disabled { background: #9fc4d6; cursor: not-allowed; }
.yxz-scene-actions a { color: #087eae; font-size: .86rem; text-decoration: underline; }

.yxz-scene-error { margin: .8rem 0 0; color: #b34646; font-size: .88rem; }

.yxz-scene-viewer {
  max-width: 72rem;
  height: min(72dvh, 48rem);
  margin: 1rem auto 0;
  overflow: hidden;
  border: 1px solid #b5dce9;
  border-radius: 1.2rem;
  background: #0b1c2c;
  box-shadow: 0 18px 50px rgba(25, 110, 150, .14);
}

.yxz-scene-viewer iframe { display: block; width: 100%; height: 100%; border: 0; }
</style>

<route lang="yaml">
name: YXZScenePage
meta:
  layout: plain
</route>
