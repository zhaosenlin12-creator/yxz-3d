<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import {
  detectYXZLocalSoftware,
  getYXZPrintApiBase,
  openYXZExportInSoftware,
} from '../../composables/use-yxz-print-preview'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [open: boolean], 'status': [status: string] }>()

interface CardResult {
  sessionId: string
  svgUrl: string
  pngUrl: string
  frontUrl: string
  backUrl: string
  sizeMm: { width: number, height: number }
  message: string
}

const form = ref({
  name: '',
  title: '',
  unit: '',
  contact: '',
  slogan: '数理创未来 智慧启新程',
  theme: '#0B5FA8',
  accent: '#F5A623',
  note: '',
  back_caption: '宜昌市第四届中小学生数理文化活动',
})
const backTemplate = ref('activity_blue')
const backTemplates = ref<Array<{ id: string, name: string, url: string }>>([])
const backPreviewUrl = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const result = ref<CardResult>()
const localSoftware = ref<Awaited<ReturnType<typeof detectYXZLocalSoftware>>>([])
const softwareLoading = ref(false)
const softwareMessage = ref('')
const openingSoftwareId = ref<string>()
const previewFontSize = computed(() => {
  const nameLen = Math.max(1, form.value.name.length)
  return nameLen <= 3 ? 30 : 22
})

const frontStyle = computed(() => ({
  background: `linear-gradient(160deg, ${form.value.theme}, ${form.value.theme}cc)`,
}))

watch(() => props.open, (open) => {
  if (open) {
    errorMessage.value = ''
    void loadTemplates()
  }
}, { immediate: true })

async function loadTemplates() {
  try {
    const response = await fetch(`${getYXZPrintApiBase()}/api/laser/templates`)
    if (!response.ok)
      throw new Error(`HTTP ${response.status}`)
    const raw: unknown = await response.json()
    const list = (raw as { templates?: Array<{ id: string, name: string, url: string }> })?.templates ?? []
    backTemplates.value = list
    if (list.length) {
      backTemplate.value = list[0].id
      backPreviewUrl.value = `${getYXZPrintApiBase()}${list[0].url}`
    }
  }
  catch {
    backPreviewUrl.value = ''
    // Non-fatal: generation will surface the real error.
  }
}

function selectBackTemplate(id: string) {
  const found = backTemplates.value.find(item => item.id === id)
  if (!found)
    return
  backTemplate.value = id
  backPreviewUrl.value = `${getYXZPrintApiBase()}${found.url}`
}

function validate(): string | null {
  if (!form.value.name.trim())
    return '请填写姓名（用于名片正面和雕刻）'
  return null
}

async function generate() {
  const problem = validate()
  if (problem) {
    errorMessage.value = problem
    return
  }
  isLoading.value = true
  errorMessage.value = ''
  result.value = undefined
  emit('status', 'processing')
  try {
    const payload = {
      ...form.value,
      back_template: backTemplate.value,
    }
    const response = await fetch(`${getYXZPrintApiBase()}/api/laser_card`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const raw: unknown = await response.json().catch(() => undefined)
    if (!response.ok) {
      const detail = (raw as { detail?: string })?.detail
      throw new Error(detail || `生成失败（HTTP ${response.status}）`)
    }
    const data = raw as {
      session_id: string
      svg_url: string
      png_url: string
      front_url: string
      back_url: string
      size_mm?: { width: number, height: number }
      message?: string
    }
    const base = getYXZPrintApiBase()
    result.value = {
      sessionId: data.session_id,
      svgUrl: `${base}${data.svg_url}`,
      pngUrl: `${base}${data.png_url}`,
      frontUrl: `${base}${data.front_url}`,
      backUrl: `${base}${data.back_url}`,
      sizeMm: data.size_mm ?? { width: 85.6, height: 54 },
      message: data.message ?? '',
    }
    emit('status', 'success')
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '名片生成失败，请稍后再试'
    emit('status', 'idle')
  }
  finally {
    isLoading.value = false
  }
}

async function detectSoftware() {
  if (softwareLoading.value)
    return
  softwareLoading.value = true
  softwareMessage.value = ''
  try {
    localSoftware.value = await detectYXZLocalSoftware()
    const available = localSoftware.value.filter(tool => tool.available)
    const laser = available.filter(tool => tool.kind === 'laser')
    if (laser.length)
      softwareMessage.value = `已找到 ${laser.length} 个激光软件：${laser.map(tool => tool.name).join('、')}`
    else if (available.length)
      softwareMessage.value = `未检测到激光软件；可用：${available.map(tool => tool.name).join('、')}（仅 3D）`
    else
      softwareMessage.value = '未检测到已安装的软件，可下载文件后手动打开'
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '软件检测失败，请确认后端服务已启动'
  }
  finally {
    softwareLoading.value = false
  }
}

async function openInSoftware(tool: Awaited<ReturnType<typeof detectYXZLocalSoftware>>[number]) {
  if (!result.value || openingSoftwareId.value)
    return
  openingSoftwareId.value = tool.id
  softwareMessage.value = ''
  try {
    await openYXZExportInSoftware({
      softwareId: tool.id,
      sessionId: result.value.sessionId,
      format: tool.kind === 'laser' ? 'svg' : 'png',
    })
    softwareMessage.value = `已打开 ${tool.name}，请在软件内确认参数后切割`
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '打开软件失败'
  }
  finally {
    openingSoftwareId.value = undefined
  }
}

function closePanel() {
  emit('update:open', false)
  emit('status', 'idle')
}

onUnmounted(() => emit('status', 'idle'))
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="yxz-laser-overlay" @click.self="closePanel">
      <section class="yxz-laser-panel" aria-label="宜小智激光切割名片">
        <header class="yxz-laser-header">
          <div>
            <strong>激光切割名片</strong>
            <small>预制模板 · 背面固定活动图，正面自由编辑 · 85.6 × 54 mm</small>
          </div>
          <button type="button" class="yxz-laser-close" aria-label="关闭名片面板" @click="closePanel">
            ×
          </button>
        </header>

        <div class="yxz-laser-grid">
          <!-- back template (fixed) -->
          <div class="yxz-laser-block">
            <span class="yxz-laser-block-label">背面 · 固定模板</span>
            <div class="yxz-laser-back">
              <img v-if="backPreviewUrl" :src="backPreviewUrl" alt="名片背面固定模板">
              <span v-else>模板加载中…</span>
            </div>
            <select v-if="backTemplates.length > 1" v-model="backTemplate" class="yxz-laser-select" @change="selectBackTemplate(backTemplate)">
              <option v-for="item in backTemplates" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select>
          </div>

          <!-- front editor -->
          <div class="yxz-laser-block">
            <span class="yxz-laser-block-label">正面 · 自由编辑</span>
            <div class="yxz-laser-preview" :style="frontStyle">
              <div class="yxz-laser-preview-slogan">
                {{ form.slogan }}
              </div>
              <div class="yxz-laser-preview-name" :style="{ fontSize: `${previewFontSize}px` }">
                {{ form.name || '姓名' }}
              </div>
              <div class="yxz-laser-preview-role">
                {{ [form.title, form.unit].filter(Boolean).join(' · ') }}
              </div>
              <div class="yxz-laser-preview-accent" :style="{ background: form.accent }" />
              <div class="yxz-laser-preview-contact">
                {{ form.contact }}
              </div>
            </div>
            <div class="yxz-laser-fields">
              <label>姓名 <input v-model="form.name" maxlength="12" placeholder="张老师"></label>
              <label>职位 <input v-model="form.title" maxlength="20" placeholder="活动组织"></label>
              <label>单位 <input v-model="form.unit" maxlength="30" placeholder="宜昌市数理文化活动组委会"></label>
              <label>标语 <input v-model="form.slogan" maxlength="30" placeholder="数理创未来 智慧启新程"></label>
              <label>联系方式 <textarea v-model="form.contact" rows="3" maxlength="120" placeholder="电话 / 微信 / 邮箱，每行一条" /></label>
              <div class="yxz-laser-colors">
                <label>主题色 <input v-model="form.theme" type="color"></label>
                <label>强调色 <input v-model="form.accent" type="color"></label>
              </div>
              <label>底部备注 <input v-model="form.note" maxlength="40" placeholder="可选"></label>
            </div>
          </div>
        </div>

        <p v-if="errorMessage" class="yxz-laser-error" role="alert">
          {{ errorMessage }}
        </p>

        <button type="button" class="yxz-laser-submit" :disabled="isLoading" @click="generate">
          {{ isLoading ? '正在生成切割文件…' : '生成激光切割文件' }}
        </button>

        <div v-if="result" class="yxz-laser-result">
          <div class="yxz-laser-result-images">
            <figure>
              <img :src="result.pngUrl" alt="名片切割预览">
              <figcaption>预览（正面 + 背面）</figcaption>
            </figure>
          </div>
          <div class="yxz-laser-result-links">
            <a :href="`${result.svgUrl}${result.svgUrl.includes('?') ? '&' : '?'}download=1`" download>下载切割 SVG</a>
            <a :href="`${result.pngUrl}${result.pngUrl.includes('?') ? '&' : '?'}download=1`" download>下载 PNG</a>
            <span>{{ result.sizeMm.width }} × {{ result.sizeMm.height }} mm</span>
          </div>
          <div class="yxz-laser-tools">
            <button type="button" class="yxz-laser-tool" :disabled="softwareLoading" @click="detectSoftware">
              {{ softwareLoading ? '检测中…' : '检测本机激光软件' }}
            </button>
            <button
              v-for="tool in localSoftware.filter(item => item.available && item.kind === 'laser')"
              :key="tool.id"
              type="button"
              class="yxz-laser-tool"
              :disabled="openingSoftwareId === tool.id"
              @click="openInSoftware(tool)"
            >
              {{ openingSoftwareId === tool.id ? '打开中…' : `打开 ${tool.name}` }}
            </button>
            <small v-if="softwareMessage" class="yxz-laser-software-message">{{ softwareMessage }}</small>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.yxz-laser-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 30, 45, .42);
  backdrop-filter: blur(4px);
}

.yxz-laser-panel {
  width: min(52rem, calc(100vw - 2rem));
  max-height: min(90vh, 52rem);
  overflow-y: auto;
  padding: 1rem;
  border: 1px solid rgba(24, 126, 180, .22);
  border-radius: 1rem;
  background: rgba(255, 255, 255, .97);
  box-shadow: 0 16px 40px rgba(24, 83, 120, .22);
  color: #15547c;
}

.yxz-laser-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: .75rem;
  margin-bottom: .8rem;
}

.yxz-laser-header strong { font-size: 1.05rem; }
.yxz-laser-header small { display: block; margin-top: .2rem; color: #6b8798; font-size: .72rem; }
.yxz-laser-close { border: 0; background: transparent; color: #62859a; font-size: 1.5rem; line-height: 1; cursor: pointer; }

.yxz-laser-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: .8rem;
}

.yxz-laser-block {
  display: flex;
  flex-direction: column;
  gap: .5rem;
  min-width: 0;
}

.yxz-laser-block-label { color: #15547c; font-size: .74rem; font-weight: 600; }

.yxz-laser-back {
  position: relative;
  overflow: hidden;
  aspect-ratio: 1.585;
  border: 1px solid #b5dce9;
  border-radius: .7rem;
  background: #f0f6fa;
}
.yxz-laser-back img { display: block; width: 100%; height: 100%; object-fit: cover; }
.yxz-laser-back span { position: absolute; inset: 0; display: grid; place-items: center; color: #52758a; font-size: .75rem; }

.yxz-laser-select {
  width: 100%;
  border: 1px solid #c8e1ec;
  border-radius: .5rem;
  padding: .35rem .5rem;
  color: #15547c;
  background: #fff;
}

.yxz-laser-preview {
  position: relative;
  overflow: hidden;
  aspect-ratio: 1.585;
  border: 1px solid #b5dce9;
  border-radius: .7rem;
  color: #fff;
  padding: 1.1rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  box-shadow: inset 0 0 40px rgba(0, 0, 0, .18);
}
.yxz-laser-preview-slogan { font-size: .62rem; opacity: .85; margin-top: .2rem; }
.yxz-laser-preview-name { font-weight: 800; line-height: 1.15; margin-top: .8rem; }
.yxz-laser-preview-role { font-size: .72rem; opacity: .9; margin-top: .55rem; }
.yxz-laser-preview-accent { width: 3.2rem; height: .24rem; border-radius: 2px; margin-top: .7rem; opacity: .9; }
.yxz-laser-preview-contact {
  margin-top: .8rem;
  font-size: .6rem;
  line-height: 1.5;
  opacity: .92;
  white-space: pre-line;
}

.yxz-laser-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .45rem;
}
.yxz-laser-fields label {
  display: flex;
  flex-direction: column;
  gap: .2rem;
  color: #52758a;
  font-size: .68rem;
}
.yxz-laser-fields label:has(textarea),
.yxz-laser-fields .yxz-laser-colors {
  grid-column: 1 / -1;
}
.yxz-laser-fields input,
.yxz-laser-fields textarea,
.yxz-laser-fields select {
  border: 1px solid #c8e1ec;
  border-radius: .45rem;
  padding: .35rem .45rem;
  color: #234b61;
  background: #fff;
  outline: none;
}
.yxz-laser-fields input:focus,
.yxz-laser-fields textarea:focus { border-color: #18a8e0; }
.yxz-laser-colors { display: flex; gap: .6rem; }
.yxz-laser-colors label { flex-direction: row; align-items: center; }
.yxz-laser-colors input[type='color'] { width: 2.2rem; height: 1.6rem; padding: 0; border: 0; background: transparent; }

.yxz-laser-error { margin: .6rem 0 0; color: #b34646; font-size: .78rem; }

.yxz-laser-submit {
  width: 100%;
  margin-top: .8rem;
  border: 1px solid #18a8e0;
  border-radius: .7rem;
  background: #18a8e0;
  color: #fff;
  padding: .6rem;
  font-size: .84rem;
  font-weight: 600;
  cursor: pointer;
}
.yxz-laser-submit:disabled { cursor: wait; opacity: .6; }

.yxz-laser-result { margin-top: .8rem; }
.yxz-laser-result-images figure { margin: 0; }
.yxz-laser-result-images img { display: block; width: 100%; border: 1px solid #b5dce9; border-radius: .6rem; }
.yxz-laser-result-images figcaption { margin-top: .3rem; color: #52758a; font-size: .68rem; }

.yxz-laser-result-links {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem .9rem;
  align-items: center;
  margin-top: .6rem;
  font-size: .75rem;
}
.yxz-laser-result-links a { color: #087eae; text-decoration: underline; }
.yxz-laser-result-links span { color: #52758a; }

.yxz-laser-tools { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; margin-top: .6rem; }
.yxz-laser-tool {
  border: 1px solid #b5dce9;
  border-radius: .45rem;
  background: #fff;
  color: #087eae;
  padding: .32rem .55rem;
  cursor: pointer;
  font-size: .7rem;
}
.yxz-laser-tool:disabled { cursor: wait; opacity: .6; }
.yxz-laser-software-message { width: 100%; color: #52758a; font-size: .68rem; }
</style>
