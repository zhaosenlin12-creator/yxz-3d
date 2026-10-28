<script setup lang="ts">
import type { ChatProvider } from '@xsai-ext/providers/utils'

import type { YXZLocalSoftware } from '../../composables/use-yxz-print-preview'
import type { ChatAssistantMessage } from '../../types/chat'

import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'

import { detectYXZLocalSoftware, openYXZExportInSoftware } from '../../composables/use-yxz-print-preview'
import { useChatOrchestratorStore } from '../../stores/chat'
import { useChatSessionStore } from '../../stores/chat/session-store'
import { useConsciousnessStore } from '../../stores/modules/consciousness'
import { useProvidersStore } from '../../stores/providers'

const props = withDefaults(defineProps<{
  open: boolean
  mode?: 'laser' | 'print'
}>(), {
  mode: 'laser',
})

const emit = defineEmits<{ 'update:open': [open: boolean], 'status': [status: string] }>()

const chatSession = useChatSessionStore()
const { messages } = storeToRefs(chatSession)
const providersStore = useProvidersStore()
const { activeProvider, activeModel } = storeToRefs(useConsciousnessStore())
const orchestrator = useChatOrchestratorStore()

const isLaser = computed(() => props.mode === 'laser')
const panelTitle = computed(() => (isLaser.value ? '激光切割工作台' : '3D 打印工作台'))
const panelSubtitle = computed(() => (isLaser.value
  ? '对话引导 → 作品预览 → 创作面板 → 3D 效果 → 导出 SVG → xTool 切割'
  : '对话引导 → 作品预览 → 创作面板 → 3D 模型 → 导出 STL → 切片打印'))

const idea = ref('')
const profile = ref({ name: '', title: '', unit: '', contact: '' })
const sending = ref(false)
const errorMessage = ref('')
const softwareMessage = ref('')
const localSoftware = ref<YXZLocalSoftware[]>([])
const openingSoftwareId = ref('')
const cardSide = ref<'front' | 'back'>('front')

const latestCreation = computed(() => {
  const list = messages.value as ChatAssistantMessage[]
  for (let index = list.length - 1; index >= 0; index--) {
    const message = list[index]
    if (message.role === 'assistant' && message.yxzCreation)
      return message.yxzCreation
  }
  return undefined
})

const latestLaserCard = computed(() => {
  const list = messages.value as ChatAssistantMessage[]
  for (let index = list.length - 1; index >= 0; index--) {
    const message = list[index]
    if (message.role === 'assistant' && message.yxzLaserCard)
      return message.yxzLaserCard
  }
  return undefined
})

const laserTools = computed(() => localSoftware.value.filter(tool => tool.kind === 'laser'))
const slicerTools = computed(() => localSoftware.value.filter(tool => tool.kind !== 'laser'))

const steps = computed(() => {
  const creation = latestCreation.value
  const card = latestLaserCard.value
  const hasModel = !!creation?.model
  const laserSteps = [
    { title: '对话确定作品', desc: '和宜小智说你想要什么作品', done: !!creation },
    { title: '生成作品预览', desc: '4 张备选方案，点头像即选定', done: !!creation },
    { title: '创作面板产出 3D', desc: '批注编辑后生成彩色 3D 效果', done: hasModel },
    { title: '导出切割 SVG', desc: '正面作品图 + 背面活动背景', done: !!card },
    { title: 'xTool 切割', desc: '确认尺寸与切割参数后出成品', done: false },
  ]
  const printSteps = [
    { title: '对话确定作品', desc: '和宜小智说你想要什么作品', done: !!creation },
    { title: '生成作品预览', desc: '4 张备选方案，点头像即选定', done: !!creation },
    { title: '创作面板产出 3D', desc: '批注编辑后生成可打印模型', done: hasModel },
    { title: '导出 STL', desc: '交给切片软件分层打印', done: hasModel },
    { title: '切片打印', desc: '确认支撑与层数后打印成品', done: false },
  ]
  return isLaser.value ? laserSteps : printSteps
})

const currentStep = computed(() => {
  const index = steps.value.findIndex(step => !step.done)
  return index < 0 ? steps.value.length : index
})

const cardImage = computed(() => {
  const card = latestLaserCard.value
  if (!card)
    return ''
  return cardSide.value === 'front' ? card.frontUrl : card.backUrl
})

const cardSizeLabel = computed(() => {
  const size = latestLaserCard.value?.sizeMm
  return size ? `${size.width} × ${size.height} mm` : '100 × 56.25 mm'
})

watch(() => props.open, (open) => {
  if (!open)
    return
  errorMessage.value = ''
  void detectSoftware()
})

async function detectSoftware() {
  try {
    localSoftware.value = await detectYXZLocalSoftware()
  }
  catch (error) {
    localSoftware.value = []
    softwareMessage.value = error instanceof Error ? error.message : '本机软件检测失败'
  }
}

function buildGuidanceText() {
  const parts: string[] = []
  const thought = idea.value.trim()
  if (thought)
    parts.push(`我的作品想法是：${thought}。`)
  const name = profile.value.name.trim()
  const title = profile.value.title.trim()
  const unit = profile.value.unit.trim()
  const contact = profile.value.contact.trim()
  const personal = [
    name && `姓名 ${name}`,
    title && `身份 ${title}`,
    unit && `学校/单位 ${unit}`,
    contact && `联系方式 ${contact}`,
  ].filter(Boolean).join('，')
  if (personal)
    parts.push(`我的个人信息：${personal}。`)
  if (isLaser.value) {
    parts.push('请先引导我一步步确认作品方案并生成预览图；我确认后，把作品图放到卡片正面、活动主视觉背景放到卡片背面，生成可以切割的 SVG 卡片。')
  }
  else {
    parts.push('请先引导我一步步确认作品方案并生成预览图；我确认后再生成可打印的 3D 模型。')
  }
  return parts.join('')
}

async function startGuidedChat() {
  if (sending.value)
    return
  const text = buildGuidanceText()
  if (!text) {
    errorMessage.value = '先写一句作品想法，或者直接点开始让宜小智来问你。'
    return
  }
  sending.value = true
  errorMessage.value = ''
  try {
    const pid = activeProvider.value
    await orchestrator.ingest(text, {
      chatProvider: await providersStore.getProviderInstance(pid) as ChatProvider,
      model: activeModel.value,
      providerConfig: providersStore.getProviderConfig(pid),
      providerId: pid,
    })
    emit('status', 'sent')
    emit('update:open', false)
  }
  catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发送失败，请稍后再试'
  }
  finally {
    sending.value = false
  }
}

function openStudio() {
  const creation = latestCreation.value
  if (!creation?.sessionId || typeof window === 'undefined')
    return
  const url = new URL('/yxz-studio', window.location.origin)
  url.searchParams.set('session', creation.sessionId)
  url.searchParams.set('image', String(creation.preview?.index ?? 0))
  url.searchParams.set('src', creation.preview?.src ?? '')
  url.searchParams.set('caption', creation.preview?.caption || creation.description || '宜小智创作方案')
  window.open(url.toString(), '_blank', 'noopener,noreferrer')
}

async function openInSoftware(tool: YXZLocalSoftware) {
  const card = latestLaserCard.value
  const creation = latestCreation.value
  const sessionId = isLaser.value ? card?.sessionId : creation?.sessionId
  if (!sessionId || openingSoftwareId.value)
    return
  openingSoftwareId.value = tool.id
  softwareMessage.value = ''
  try {
    const response = await openYXZExportInSoftware({
      softwareId: tool.id,
      sessionId,
      format: isLaser.value ? 'svg' : 'stl',
    }) as any
    const data = response?.data ?? response
    softwareMessage.value = data?.message || `已打开 ${tool.name}，请确认参数后继续`
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '打开软件失败'
  }
  finally {
    openingSoftwareId.value = ''
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="yxz-wb-overlay" @click.self="emit('update:open', false)">
      <section class="yxz-wb-panel" :aria-label="panelTitle">
        <header class="yxz-wb-header">
          <div>
            <strong>{{ panelTitle }}</strong>
            <small>{{ panelSubtitle }}</small>
          </div>
          <button type="button" class="yxz-wb-close" aria-label="关闭工作台" @click="emit('update:open', false)">
            ×
          </button>
        </header>

        <div class="yxz-wb-body">
          <div class="yxz-wb-column">
            <span class="yxz-wb-label">制作流程</span>
            <ol class="yxz-wb-steps">
              <li
                v-for="(step, index) in steps"
                :key="step.title"
                :class="{ 'is-done': step.done, 'is-current': !step.done && index === currentStep }"
              >
                <span class="yxz-wb-step-index">{{ index + 1 }}</span>
                <span class="yxz-wb-step-text">
                  <strong>{{ step.title }}</strong>
                  <small>{{ step.desc }}</small>
                </span>
              </li>
            </ol>

            <span class="yxz-wb-label">作品想法与个人信息</span>
            <textarea
              v-model="idea"
              rows="2"
              maxlength="120"
              placeholder="例：校徽风格的校园纪念徽章，圆角，蓝色金属质感"
              aria-label="作品想法"
            />
            <div class="yxz-wb-fields">
              <label>姓名 <input v-model="profile.name" maxlength="12" placeholder="张三"></label>
              <label>身份 <input v-model="profile.title" maxlength="20" placeholder="学生"></label>
              <label>学校 <input v-model="profile.unit" maxlength="30" placeholder="宜昌市实验中学"></label>
              <label>联系方式 <input v-model="profile.contact" maxlength="60" placeholder="电话 / 微信"></label>
            </div>
            <button type="button" class="yxz-wb-primary" :disabled="sending" @click="startGuidedChat">
              {{ sending ? '正在发送…' : '开始对话引导' }}
            </button>
            <p v-if="errorMessage" class="yxz-wb-error">
              {{ errorMessage }}
            </p>
          </div>

          <div class="yxz-wb-column">
            <span class="yxz-wb-label">当前作品预览</span>
            <div v-if="latestCreation" class="yxz-wb-preview">
              <img :src="latestCreation.preview?.src" :alt="latestCreation.preview?.caption || '作品预览'">
            </div>
            <p v-else class="yxz-wb-empty">
              还没有作品预览。点「开始对话引导」，宜小智会一步步问你并生成预览图。
            </p>
            <button
              v-if="latestCreation"
              type="button"
              class="yxz-wb-secondary"
              @click="openStudio"
            >
              打开创作面板
            </button>

            <template v-if="isLaser">
              <span class="yxz-wb-label">切割卡片</span>
              <div v-if="latestLaserCard" class="yxz-wb-preview">
                <img :src="cardImage" :alt="cardSide === 'front' ? '卡片正面' : '卡片背面'">
              </div>
              <p v-else class="yxz-wb-empty">
                卡片还没生成。确认作品与个人信息后，宜小智会调用激光切割工具出卡片。
              </p>
              <div v-if="latestLaserCard" class="yxz-wb-card-actions">
                <div class="yxz-wb-tabs">
                  <button type="button" :class="{ active: cardSide === 'front' }" @click="cardSide = 'front'">
                    正面 · 作品
                  </button>
                  <button type="button" :class="{ active: cardSide === 'back' }" @click="cardSide = 'back'">
                    背面 · 活动背景
                  </button>
                </div>
                <p class="yxz-wb-hint">
                  尺寸 {{ cardSizeLabel }} · 背面固定活动主视觉，正面是你的作品图，SVG 已内嵌作品图。
                </p>
                <div class="yxz-wb-buttons">
                  <a :href="latestLaserCard.svgUrl" download rel="noreferrer">下载切割 SVG</a>
                  <a :href="latestLaserCard.pngUrl" target="_blank" rel="noopener noreferrer">打开整卡预览</a>
                </div>
              </div>
            </template>
          </div>
        </div>

        <footer class="yxz-wb-footer">
          <span class="yxz-wb-label">本机软件</span>
          <div class="yxz-wb-tools">
            <template v-if="isLaser">
              <button
                v-for="tool in laserTools"
                :key="tool.id"
                type="button"
                :disabled="!latestLaserCard || !!openingSoftwareId"
                @click="openInSoftware(tool)"
              >
                用 {{ tool.name }} 打开切割
              </button>
              <span v-if="!laserTools.length" class="yxz-wb-hint">未检测到激光软件，可下载 SVG 后手动导入 xTool。</span>
            </template>
            <template v-else>
              <button
                v-for="tool in slicerTools"
                :key="tool.id"
                type="button"
                :disabled="!latestCreation?.model || !!openingSoftwareId"
                @click="openInSoftware(tool)"
              >
                用 {{ tool.name }} 打开模型
              </button>
              <span v-if="!slicerTools.length" class="yxz-wb-hint">未检测到切片软件，可下载 STL 后手动打开。</span>
            </template>
          </div>
          <p v-if="softwareMessage" class="yxz-wb-hint">
            {{ softwareMessage }}
          </p>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.yxz-wb-overlay {
  position: fixed;
  inset: 0;
  z-index: 9998;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: rgba(6, 18, 32, .55);
  backdrop-filter: blur(3px);
}

.yxz-wb-panel {
  display: flex;
  flex-direction: column;
  gap: .9rem;
  width: min(62rem, 100%);
  max-height: min(88vh, 52rem);
  overflow: hidden auto;
  border: 1px solid #b5dce9;
  border-radius: 1rem;
  background: #f7fbfe;
  color: #234b61;
  padding: 1rem 1.1rem 1.1rem;
  box-shadow: 0 24px 70px rgba(4, 20, 38, .35);
}

.yxz-wb-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: .8rem;
}

.yxz-wb-header strong { font-size: 1.05rem; color: #15547c; }
.yxz-wb-header small { display: block; margin-top: .2rem; color: #6b8798; font-size: .72rem; }
.yxz-wb-close { border: 0; background: transparent; color: #62859a; font-size: 1.5rem; line-height: 1; cursor: pointer; }

.yxz-wb-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1.1rem;
}

.yxz-wb-column {
  display: flex;
  flex-direction: column;
  gap: .5rem;
  min-width: 0;
}

.yxz-wb-label { color: #15547c; font-size: .74rem; font-weight: 600; }

.yxz-wb-steps {
  display: flex;
  flex-direction: column;
  gap: .35rem;
  margin: 0 0 .3rem;
  padding: 0;
  list-style: none;
}

.yxz-wb-steps li {
  display: flex;
  align-items: center;
  gap: .55rem;
  border: 1px solid #d6e8f1;
  border-radius: .55rem;
  background: #fff;
  padding: .4rem .55rem;
}

.yxz-wb-step-index {
  display: grid;
  place-items: center;
  flex: none;
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 999px;
  background: #e3f1f8;
  color: #52758a;
  font-size: .72rem;
  font-weight: 700;
}

.yxz-wb-steps li.is-done .yxz-wb-step-index { background: #18a8e0; color: #fff; }
.yxz-wb-steps li.is-current { border-color: #18a8e0; background: rgba(24, 168, 224, .07); }
.yxz-wb-steps li.is-current .yxz-wb-step-index { background: #18a8e0; color: #fff; }

.yxz-wb-step-text { display: flex; flex-direction: column; min-width: 0; }
.yxz-wb-step-text strong { font-size: .78rem; color: #15547c; }
.yxz-wb-step-text small { color: #7b95a6; font-size: .68rem; }

.yxz-wb-panel textarea,
.yxz-wb-panel input {
  border: 1px solid #c8e1ec;
  border-radius: .45rem;
  padding: .38rem .5rem;
  color: #234b61;
  background: #fff;
  outline: none;
  font-size: .72rem;
}

.yxz-wb-panel textarea:focus,
.yxz-wb-panel input:focus { border-color: #18a8e0; }
.yxz-wb-panel textarea { resize: vertical; width: 100%; }

.yxz-wb-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .4rem;
}

.yxz-wb-fields label {
  display: flex;
  flex-direction: column;
  gap: .18rem;
  color: #52758a;
  font-size: .66rem;
}

.yxz-wb-primary {
  width: 100%;
  border: 1px solid #18a8e0;
  border-radius: .6rem;
  background: #18a8e0;
  color: #fff;
  padding: .55rem;
  font-size: .8rem;
  font-weight: 600;
  cursor: pointer;
}

.yxz-wb-primary:disabled { cursor: wait; opacity: .6; }

.yxz-wb-secondary {
  align-self: flex-start;
  border: 1px solid #18a8e0;
  border-radius: .5rem;
  background: rgba(24, 168, 224, .1);
  color: #087eae;
  padding: .38rem .7rem;
  font-size: .74rem;
  font-weight: 600;
  cursor: pointer;
}

.yxz-wb-preview {
  overflow: hidden;
  border: 1px solid #b5dce9;
  border-radius: .6rem;
  background: #fff;
}

.yxz-wb-preview img { display: block; width: 100%; max-height: 15rem; object-fit: contain; background: #f3f8fb; }

.yxz-wb-empty {
  margin: 0;
  border: 1px dashed #b5dce9;
  border-radius: .6rem;
  padding: .8rem;
  color: #7b95a6;
  font-size: .72rem;
  line-height: 1.6;
}

.yxz-wb-card-actions { display: flex; flex-direction: column; gap: .45rem; }

.yxz-wb-tabs { display: flex; gap: .35rem; }

.yxz-wb-tabs button {
  flex: 1;
  border: 1px solid #c8e1ec;
  border-radius: .45rem;
  background: #fff;
  color: #52758a;
  padding: .3rem .4rem;
  cursor: pointer;
  font-size: .7rem;
}

.yxz-wb-tabs button.active { border-color: #18a8e0; background: rgba(24, 168, 224, .1); color: #087eae; font-weight: 600; }

.yxz-wb-hint { margin: 0; color: #52758a; font-size: .68rem; line-height: 1.55; }
.yxz-wb-error { margin: 0; color: #b34646; font-size: .72rem; }

.yxz-wb-buttons { display: flex; flex-wrap: wrap; gap: .45rem; }

.yxz-wb-buttons a,
.yxz-wb-tools button {
  border: 1px solid #b5dce9;
  border-radius: .45rem;
  background: #fff;
  color: #087eae;
  padding: .32rem .55rem;
  cursor: pointer;
  font-size: .7rem;
  text-decoration: none;
}

.yxz-wb-tools button:disabled { cursor: not-allowed; opacity: .5; }

.yxz-wb-footer {
  display: flex;
  flex-direction: column;
  gap: .4rem;
  border-top: 1px solid #dcecf3;
  padding-top: .7rem;
}

.yxz-wb-tools { display: flex; flex-wrap: wrap; gap: .45rem; align-items: center; }

@media (max-width: 780px) {
  .yxz-wb-body { grid-template-columns: minmax(0, 1fr); }
  .yxz-wb-fields { grid-template-columns: 1fr; }
}
</style>
