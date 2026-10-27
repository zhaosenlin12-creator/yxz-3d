<script setup lang="ts">
import type { YXZInteractionStatus } from '../../assets/yxz/interaction'
import type { ChatHistoryItem, YXZCreationPayload } from '../../types/chat'

import { nanoid } from 'nanoid'
import { computed, onUnmounted, ref } from 'vue'

import YXZCreationMessageCard from './YXZCreationMessageCard.vue'
import YXZPreviewCanvasEditor from './YXZPreviewCanvasEditor.vue'

import {
  buildYXZPreviewPrompt,
  createYXZCartoonModel,
  createYXZPreview,
  detectYXZLocalSoftware,
  openYXZExportInSoftware,
  previewImageSrc,
} from '../../composables/use-yxz-print-preview'
import { getYXZRequirementNextQuestion, useYXZRequirementMemory } from '../../composables/use-yxz-requirement-memory'
import { useChatSessionStore } from '../../stores/chat/session-store'

const emit = defineEmits<{
  status: [status: YXZInteractionStatus]
}>()

const options = [
  '圆润可爱',
  '简洁造型',
  '适合 3D 打印',
  '单色模型',
  '保留明显轮廓',
] as const

const chatSession = useChatSessionStore()
const requirementMemory = useYXZRequirementMemory()
const storedRequirement = requirementMemory.state.value
const isOpen = ref(false)
const description = ref(storedRequirement?.description ?? '')
const selectedOptions = ref<string[]>(storedRequirement?.constraints.length
  ? storedRequirement.constraints.filter(option => options.includes(option as typeof options[number]))
  : ['圆润可爱', '适合 3D 打印'])
const previews = ref<Array<{ index: number, src: string, caption: string }>>([])
const sessionId = ref<string>()
const selectedIndex = ref<number>()
const model = ref<{ modelUrl: string, stlUrl: string, glbUrl: string }>()
const editedPreviewSrc = ref<string>()
const isEditing = ref(false)
const modelProgress = ref({ percent: 0, message: '' })
const errorMessage = ref('')
const isLoading = ref(false)
const isModelLoading = ref(false)
const localSoftware = ref<Awaited<ReturnType<typeof detectYXZLocalSoftware>>>([])
const softwareLoading = ref(false)
const softwareMessage = ref('')
const openingSoftwareId = ref<string>()
const controller = ref<AbortController>()
const chatMessageId = ref<string>()
let persistVersion = 0

const buttonLabel = computed(() => isLoading.value ? '正在生成…' : '生成预览')
const modelButtonLabel = computed(() => isModelLoading.value ? `正在制作 ${modelProgress.value.percent}%` : '生成可打印 3D 文件')
const selectedPreview = computed(() => previews.value.find(preview => preview.index === selectedIndex.value))
const displayedPreview = computed(() => {
  const preview = selectedPreview.value
  return preview ? { ...preview, src: editedPreviewSrc.value ?? preview.src } : undefined
})
const nextQuestion = computed(() => getYXZRequirementNextQuestion(requirementMemory.state.value))

function rememberCurrentRequirement() {
  requirementMemory.update({
    description: description.value,
    constraints: selectedOptions.value,
  })
}

async function persistCreation(status: YXZCreationPayload['status']) {
  const preview = displayedPreview.value
  if (!preview)
    return

  const version = ++persistVersion
  const descriptionSnapshot = description.value.trim()
  const optionsSnapshot = [...selectedOptions.value]
  const modelSnapshot = model.value

  try {
    await chatSession.initialize()
    if (version !== persistVersion)
      return

    const activeSessionId = chatSession.activeSessionId
    if (!activeSessionId)
      return

    const text = `我已整理好「${preview.caption}」创作方案，你可以继续确认预览或进入 3D 制作。`
    const message: ChatHistoryItem = {
      role: 'assistant',
      content: text,
      slices: [{ type: 'text', text }],
      tool_results: [],
      yxzCreation: {
        kind: 'yxz-creation',
        sessionId: sessionId.value,
        description: descriptionSnapshot,
        options: optionsSnapshot,
        preview,
        model: modelSnapshot,
        status,
      },
      createdAt: Date.now(),
      id: chatMessageId.value ?? nanoid(),
    }

    const messages = chatSession.getSessionMessages(activeSessionId)
    const existingIndex = messages.findIndex(item => item.id === chatMessageId.value)
    if (existingIndex >= 0) {
      const next = [...messages]
      next[existingIndex] = message
      chatSession.setSessionMessages(activeSessionId, next)
    }
    else {
      chatMessageId.value = message.id
      chatSession.appendSessionMessage(activeSessionId, message)
    }
  }
  catch {
    // Preview generation remains usable even when chat persistence is unavailable.
  }
}

function toggleOption(option: string) {
  selectedOptions.value = selectedOptions.value.includes(option)
    ? selectedOptions.value.filter(item => item !== option)
    : [...selectedOptions.value, option]
}

function selectPreview(index: number) {
  selectedIndex.value = index
  model.value = undefined
  editedPreviewSrc.value = undefined
  isEditing.value = false
  void persistCreation('preview')
}

function applyCanvasEdit(dataUrl: string) {
  editedPreviewSrc.value = dataUrl
  model.value = undefined
  isEditing.value = false
  void persistCreation('preview')
}

const refineInstruction = ref('')
const isRefining = ref(false)

/** Send the annotated canvas + instruction to the AI image editor, then swap
 *  the returned revision into the preview grid as the newest candidate. */
async function handleRefine(dataUrl: string) {
  if (isRefining.value || !sessionId.value)
    return
  isRefining.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`${getYXZPrintApiBase()}/api/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId.value,
        instruction: refineInstruction.value.trim() || '请根据画布上的批注修改一版，其余保持大致不变',
        image: dataUrl,
      }),
    })
    const raw: unknown = await response.json().catch(() => undefined)
    if (!response.ok) {
      const detail = (raw as { detail?: string })?.detail
      throw new Error(detail || `AI 修改失败（HTTP ${response.status}）`)
    }
    const items = (raw as { previews?: Array<{ index?: number, b64?: string, path?: string }> })?.previews
    const item = items?.[0]
    if (!item || (!item.b64 && !item.path))
      throw new Error('后台没有返回修改结果，请稍后重试')
    const src = previewImageSrc(item)
    const newIndex = (previews.value.reduce((max, preview) => Math.max(max, preview.index), -1) + 1)
    previews.value = [...previews.value, { index: newIndex, src, caption: '按批注修改 · 新版' }]
    editedPreviewSrc.value = undefined
    isEditing.value = false
    selectedIndex.value = newIndex
    refineInstruction.value = ''
    void persistCreation('preview')
    emit('status', 'success')
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'AI 按批注修改失败，请稍后重试'
    emit('status', 'idle')
  }
  finally {
    isRefining.value = false
  }
}

function openPanel() {
  isOpen.value = true
}

function clearRequirementMemory() {
  requirementMemory.clear()
  description.value = ''
  selectedOptions.value = ['圆润可爱', '适合 3D 打印']
}

async function detectLocalSoftware() {
  if (softwareLoading.value)
    return
  softwareLoading.value = true
  softwareMessage.value = ''
  try {
    localSoftware.value = await detectYXZLocalSoftware()
    const count = localSoftware.value.filter(tool => tool.available).length
    softwareMessage.value = count ? `已找到 ${count} 个可用软件` : '暂未找到已安装的软件'
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '软件检测失败，请确认打印服务已启动'
  }
  finally {
    softwareLoading.value = false
  }
}

async function openInLocalSoftware(tool: Awaited<ReturnType<typeof detectYXZLocalSoftware>>[number]) {
  if (!model.value || !sessionId.value || openingSoftwareId.value)
    return
  openingSoftwareId.value = tool.id
  softwareMessage.value = ''
  softwareLoading.value = true
  try {
    const format = tool.kind === 'laser' ? 'png' : (tool.kind === '3d-edit' ? 'glb' : 'stl')
    const resp = await openYXZExportInSoftware({ softwareId: tool.id, sessionId: sessionId.value, format })
    const data = (resp as any)?.data ?? (resp as any)
    if (data?.method === 'manual') {
      const filePath = data?.file
      if (filePath) {
        try {
          await navigator.clipboard.writeText(filePath)
        }
        catch { /* clipboard unavailable */ }
      }
      softwareMessage.value = data?.message || `已打开 ${tool.name}；该软件需手动导入，文件路径已复制，请在软件内导入后粘贴路径。`
    }
    else {
      softwareMessage.value = data?.message || `已打开 ${tool.name} 并加载模型，请确认参数后再打印或切割`
    }
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '打开软件失败'
  }
  finally {
    softwareLoading.value = false
    openingSoftwareId.value = undefined
  }
}

async function generatePreview() {
  if (isLoading.value)
    return

  errorMessage.value = ''
  rememberCurrentRequirement()
  previews.value = []
  editedPreviewSrc.value = undefined
  isEditing.value = false
  controller.value?.abort()
  controller.value = new AbortController()
  isLoading.value = true
  emit('status', 'processing')

  try {
    const result = await createYXZPreview({
      prompt: buildYXZPreviewPrompt(description.value, selectedOptions.value),
      sessionId: sessionId.value,
      signal: controller.value.signal,
    })
    sessionId.value = result.sessionId
    previews.value = result.previews.map(item => ({
      index: item.index,
      src: previewImageSrc(item),
      caption: item.caption ?? `方案 ${item.index + 1}`,
    }))
    selectedIndex.value = result.previews[0]?.index
    model.value = undefined
    void persistCreation('preview')
    emit('status', 'success')
  }
  catch (error) {
    if ((error as Error)?.name !== 'AbortError') {
      errorMessage.value = error instanceof Error ? error.message : '预览生成失败，请稍后再试'
      emit('status', 'idle')
    }
  }
  finally {
    isLoading.value = false
    controller.value = undefined
  }
}

async function generateModel() {
  if (isModelLoading.value || !sessionId.value || selectedIndex.value === undefined)
    return

  errorMessage.value = ''
  model.value = undefined
  isModelLoading.value = true
  modelProgress.value = { percent: 0, message: '准备生成 3D 模型…' }
  emit('status', 'processing')
  controller.value?.abort()
  controller.value = new AbortController()

  try {
    model.value = await createYXZCartoonModel({
      sessionId: sessionId.value,
      imageIndex: selectedIndex.value,
      customImage: editedPreviewSrc.value,
      signal: controller.value.signal,
      onProgress: (progress) => {
        modelProgress.value = { percent: Math.max(0, Math.min(100, progress.percent)), message: progress.message }
      },
    })
    void persistCreation('model-ready')
    emit('status', 'success')
  }
  catch (error) {
    if ((error as Error)?.name !== 'AbortError') {
      errorMessage.value = error instanceof Error ? error.message : '3D 生成失败，请稍后再试'
      emit('status', 'idle')
    }
  }
  finally {
    isModelLoading.value = false
    controller.value = undefined
  }
}

function closePanel() {
  controller.value?.abort()
  isEditing.value = false
  isOpen.value = false
  emit('status', 'idle')
}

onUnmounted(() => controller.value?.abort())
</script>

<template>
  <div class="yxz-print-preview">
    <button
      v-if="!isOpen"
      type="button"
      class="yxz-print-launch"
      aria-label="打开宜小智创作面板"
      @click="openPanel"
    >
      <span class="yxz-print-launch-dot" />
      <span>打开创作面板</span>
    </button>

    <section v-else class="yxz-print-panel" aria-label="宜小智产品预览">
      <header class="yxz-print-header">
        <div>
          <strong>宜小智创作工作台</strong>
          <small>聊天负责沟通，这里负责设计、画布编辑和 3D 文件输出</small>
        </div>
        <div class="yxz-print-header-actions">
          <a
            v-if="sessionId"
            class="yxz-print-open-studio"
            :href="`/yxz-studio?session=${encodeURIComponent(sessionId)}`"
            target="_blank"
            rel="noopener noreferrer"
          >
            在新标签页打开创作面板 ↗
          </a>
          <button type="button" class="yxz-print-memory-clear" @click="clearRequirementMemory">
            清除记忆
          </button>
          <button type="button" class="yxz-print-close" aria-label="关闭预览面板" @click="closePanel">
            ×
          </button>
        </div>
      </header>

      <ol class="yxz-print-steps" aria-label="创作步骤">
        <li class="active"><span>1</span>描述想法</li>
        <li :class="{ active: previews.length }"><span>2</span>确认预览</li>
        <li :class="{ active: editedPreviewSrc }"><span>3</span>画布个性化</li>
        <li :class="{ active: model }"><span>4</span>生成 3D</li>
      </ol>

      <label class="yxz-print-field-label" for="yxz-product-description">产品想法</label>
      <textarea
        id="yxz-product-description"
        v-model="description"
        class="yxz-print-input"
        rows="3"
        maxlength="500"
        placeholder="例如：一个戴着红围巾的小熊桌面摆件"
        :disabled="isLoading"
      />
      <p class="yxz-print-hint" role="status">
        宜小智：{{ nextQuestion }}
      </p>
      <div class="yxz-print-options" aria-label="设计约束">
        <button
          v-for="option in options"
          :key="option"
          type="button"
          class="yxz-print-chip"
          :class="{ active: selectedOptions.includes(option) }"
          :aria-pressed="selectedOptions.includes(option)"
          :disabled="isLoading"
          @click="toggleOption(option)"
        >
          {{ option }}
        </button>
      </div>
      <button type="button" class="yxz-print-submit" :disabled="isLoading || !description.trim()" @click="generatePreview">
        {{ buttonLabel }}
      </button>
      <p v-if="errorMessage" class="yxz-print-error" role="alert">
        {{ errorMessage }}
      </p>
      <div v-if="previews.length" class="yxz-print-grid" aria-live="polite">
        <figure v-for="preview in previews" :key="preview.src" class="yxz-print-card">
          <button type="button" class="yxz-print-card-button" :class="{ selected: selectedIndex === preview.index }" :aria-label="`选择${preview.caption}`" @click="selectPreview(preview.index)">
            <img :src="preview.src" :alt="preview.caption" loading="lazy" decoding="async">
          </button>
          <figcaption>{{ preview.caption }}</figcaption>
        </figure>
      </div>
      <div v-if="displayedPreview" class="yxz-print-edit-actions">
        <span>{{ editedPreviewSrc ? '已应用个性化画布' : '想加名字、符号或颜色？可以直接编辑预览' }}</span>
        <button type="button" @click="isEditing = !isEditing">
          {{ isEditing ? '收起画布' : '打开画布编辑' }}
        </button>
      </div>
      <div v-if="isEditing" class="yxz-print-refine-row">
        <input
          v-model="refineInstruction"
          type="text"
          maxlength="200"
          placeholder="告诉 AI 怎么改（可留空，AI 会看图上的批注）"
          aria-label="AI 修改指令"
        >
        <small v-if="isRefining" class="yxz-print-refine-status">AI 正在按批注修改，请耐心等待…</small>
      </div>
      <YXZPreviewCanvasEditor
        v-if="displayedPreview && isEditing"
        :image-src="displayedPreview.src"
        :caption="displayedPreview.caption"
        @save="applyCanvasEdit"
        @refine="handleRefine"
        @close="isEditing = false"
      />
      <YXZCreationMessageCard
        v-if="displayedPreview"
        :preview-src="displayedPreview.src"
        :caption="displayedPreview.caption"
        :description="description"
        :previews="previews.map(p => ({ index: p.index, src: p.src, caption: p.caption }))"
        :model-url="model?.modelUrl"
        :stl-url="model?.stlUrl"
        :session-id="sessionId"
        :status="isModelLoading ? 'model-building' : (model ? 'model-ready' : 'preview')"
        :progress-msg="modelProgress.message"
        @adopt="void persistCreation('adopted'); emit('status', 'success')"
        @redescribe="model = undefined; void persistCreation('redescribe')"
      />
      <div v-if="previews.length" class="yxz-print-model-actions">
        <button type="button" class="yxz-print-submit" :disabled="isModelLoading || selectedIndex === undefined" @click="generateModel">
          {{ modelButtonLabel }}
        </button>
        <div v-if="isModelLoading" class="yxz-print-progress" role="status" aria-live="polite">
          <span :style="{ width: `${modelProgress.percent}%` }" />
          <small>{{ modelProgress.message }}</small>
        </div>
        <div v-if="model" class="yxz-print-model-result">
          <span>3D 模型已生成，可打开预览、下载或交给本机软件继续处理。</span>
          <button type="button" class="yxz-print-tool-detect" :disabled="softwareLoading" @click="detectLocalSoftware">
            {{ softwareLoading ? '检测中…' : '检测本机软件' }}
          </button>
          <div v-if="localSoftware.some(tool => tool.available)" class="yxz-print-tools" aria-label="本机软件">
            <button
              v-for="tool in localSoftware.filter(tool => tool.available && (tool.kind === '3d-print' || tool.kind === 'laser' || tool.kind === '3d-edit'))"
              :key="tool.id"
              type="button"
              class="yxz-print-tool"
              :disabled="openingSoftwareId === tool.id"
              @click="openInLocalSoftware(tool)"
            >
              {{ openingSoftwareId === tool.id ? '打开中…' : `打开 ${tool.name}` }}
            </button>
          </div>
          <small v-if="softwareMessage" class="yxz-print-software-message">{{ softwareMessage }}</small>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.yxz-print-preview {
  position: absolute;
  right: 1rem;
  bottom: 1rem;
  z-index: 20;
  font-family: inherit;
}

.yxz-print-launch,
.yxz-print-submit {
  display: inline-flex;
  align-items: center;
  gap: .5rem;
  border: 1px solid rgba(24, 126, 180, .34);
  border-radius: 999px;
  background: rgba(255, 255, 255, .94);
  color: #15547c;
  padding: .55rem .9rem;
  box-shadow: 0 8px 24px rgba(27, 111, 177, .15);
  cursor: pointer;
}

.yxz-print-launch:hover,
.yxz-print-submit:hover:not(:disabled) {
  background: #f1fbff;
}

.yxz-print-launch-dot {
  width: .55rem;
  height: .55rem;
  border-radius: 50%;
  background: #18a8e0;
  box-shadow: 0 0 0 4px rgba(24, 168, 224, .12);
}

.yxz-print-panel {
  width: min(31rem, calc(100vw - 2rem));
  max-height: min(82vh, 48rem);
  overflow-y: auto;
  padding: 1rem;
  border: 1px solid rgba(24, 126, 180, .22);
  border-radius: 1rem;
  background: rgba(255, 255, 255, .96);
  box-shadow: 0 16px 40px rgba(24, 83, 120, .18);
  backdrop-filter: blur(14px);
}

.yxz-print-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .35rem;
  margin: 0 0 .85rem;
  padding: 0;
  list-style: none;
}

.yxz-print-steps li {
  display: flex;
  align-items: center;
  gap: .25rem;
  color: #8aa4b2;
  font-size: .62rem;
  line-height: 1.2;
}

.yxz-print-steps span {
  display: inline-grid;
  width: 1.25rem;
  height: 1.25rem;
  flex: none;
  place-items: center;
  border: 1px solid #c8e1ec;
  border-radius: 50%;
  background: #fff;
}

.yxz-print-steps li.active {
  color: #15547c;
}

.yxz-print-steps li.active span {
  border-color: #18a8e0;
  background: #eaf8fd;
  color: #087eae;
}

.yxz-print-field-label {
  display: block;
  margin-bottom: .3rem;
  color: #15547c;
  font-size: .72rem;
  font-weight: 600;
}

.yxz-print-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: .75rem;
  margin-bottom: .8rem;
  color: #15547c;
}

.yxz-print-header-actions {
  display: flex;
  align-items: center;
  gap: .35rem;
}

.yxz-print-header strong,
.yxz-print-header small {
  display: block;
}

.yxz-print-header small,
.yxz-print-endpoint {
  margin-top: .2rem;
  color: #6b8798;
  font-size: .72rem;
}

.yxz-print-close {
  border: 0;
  background: transparent;
  color: #62859a;
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
}

.yxz-print-memory-clear {
  border: 0;
  background: transparent;
  color: #6b8798;
  font-size: .68rem;
  cursor: pointer;
}

.yxz-print-memory-clear:hover {
  color: #087eae;
  text-decoration: underline;
}

.yxz-print-input {
  width: 100%;
  resize: vertical;
  border: 1px solid #c8e1ec;
  border-radius: .7rem;
  padding: .65rem .7rem;
  color: #234b61;
  outline: none;
}

.yxz-print-input:focus {
  border-color: #18a8e0;
  box-shadow: 0 0 0 3px rgba(24, 168, 224, .12);
}

.yxz-print-hint {
  margin: .45rem 0 0;
  color: #52758a;
  font-size: .72rem;
  line-height: 1.45;
}

.yxz-print-edit-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  margin-top: .75rem;
  color: #52758a;
  font-size: .7rem;
}

.yxz-print-refine-row {
  display: flex;
  flex-direction: column;
  gap: .4rem;
  margin-top: .5rem;
}

.yxz-print-refine-row input {
  border: 1px solid #c8e1ec;
  border-radius: .55rem;
  padding: .4rem .55rem;
  color: #234b61;
  font-size: .72rem;
  width: 100%;
}

.yxz-print-refine-status {
  color: #087eae;
  font-size: .7rem;
}

.yxz-print-edit-actions button {
  flex: none;
  border: 1px solid #18a8e0;
  border-radius: .55rem;
  background: #fff;
  color: #087eae;
  padding: .35rem .55rem;
  cursor: pointer;
  font-size: .7rem;
}

.yxz-print-options {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin: .7rem 0;
}

.yxz-print-chip {
  border: 1px solid #c8e1ec;
  border-radius: 999px;
  background: #fff;
  color: #44738b;
  padding: .25rem .55rem;
  font-size: .72rem;
  cursor: pointer;
}

.yxz-print-chip.active {
  border-color: #18a8e0;
  background: #eaf8fd;
  color: #15547c;
}

.yxz-print-submit {
  width: 100%;
  justify-content: center;
  border-radius: .7rem;
  background: #eaf8fd;
}

.yxz-print-submit:disabled,
.yxz-print-chip:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.yxz-print-error {
  margin: .7rem 0 0;
  color: #b34646;
  font-size: .78rem;
}

.yxz-print-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .55rem;
  margin-top: .8rem;
}

.yxz-print-card {
  overflow: hidden;
  margin: 0;
  border: 1px solid #d7eaf1;
  border-radius: .7rem;
  background: #f6fbfd;
}

.yxz-print-card-button {
  display: block;
  width: 100%;
  padding: 0;
  border: 2px solid transparent;
  background: transparent;
  cursor: pointer;
}

.yxz-print-card-button.selected {
  border-color: #18a8e0;
}

.yxz-print-card img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}

.yxz-print-model-actions {
  margin-top: .8rem;
}

.yxz-print-progress {
  overflow: hidden;
  margin-top: .55rem;
  border-radius: .5rem;
  background: #e5f1f5;
}

.yxz-print-progress > span {
  display: block;
  height: .35rem;
  background: #18a8e0;
  transition: width 300ms ease;
}

.yxz-print-progress small {
  display: block;
  padding: .35rem .45rem;
  color: #52758a;
  font-size: .7rem;
}

.yxz-print-model-result {
  display: flex;
  flex-wrap: wrap;
  gap: .45rem .7rem;
  align-items: center;
  margin-top: .6rem;
  color: #15547c;
  font-size: .75rem;
}

.yxz-print-model-result a {
  color: #087eae;
  text-decoration: underline;
}

.yxz-print-tool-detect,
.yxz-print-tool {
  border: 1px solid #b5dce9;
  border-radius: .45rem;
  background: #fff;
  color: #087eae;
  padding: .3rem .5rem;
  cursor: pointer;
  font-size: .68rem;
}

.yxz-print-tool-detect:disabled,
.yxz-print-tool:disabled {
  cursor: wait;
  opacity: .6;
}

.yxz-print-tools {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem;
  width: 100%;
}

.yxz-print-software-message {
  width: 100%;
  color: #52758a;
  font-size: .68rem;
}

.yxz-print-card figcaption {
  overflow: hidden;
  padding: .35rem .45rem;
  color: #52758a;
  font-size: .68rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
