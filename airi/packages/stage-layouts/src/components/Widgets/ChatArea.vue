<script setup lang="ts">
import type { ChatProvider } from '@xsai-ext/providers/utils'

import { YXZCreationWorkbench } from '@proj-airi/stage-ui/components/scenes'
import { getYXZPrintApiBase } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'
import { useYXZVoiceInput } from '@proj-airi/stage-ui/composables/use-yxz-voice-input'
import { useChatOrchestratorStore } from '@proj-airi/stage-ui/stores/chat'
import { useChatSessionStore } from '@proj-airi/stage-ui/stores/chat/session-store'
import { useChatStreamStore } from '@proj-airi/stage-ui/stores/chat/stream-store'
import { resolveFallbackCandidates } from '@proj-airi/stage-ui/stores/llm'
import { useConsciousnessStore } from '@proj-airi/stage-ui/stores/modules/consciousness'
import { useHearingStore } from '@proj-airi/stage-ui/stores/modules/hearing'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { BasicTextarea, FieldCombobox } from '@proj-airi/ui'
import { useLocalStorage } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { DropdownMenuContent, DropdownMenuItem, DropdownMenuPortal, DropdownMenuRoot, DropdownMenuTrigger, PopoverContent, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'

import CameraCapture from './CameraCapture.vue'

import { ChatSendTimeoutError, notifyYXZChatRecovery, withChatSendTimeout } from './chat-send-recovery'

const messageInput = ref('')
const hearingPopoverOpen = ref(false)
const isComposing = ref(false)
const workbenchOpen = ref(false)
const workbenchMode = ref<'laser' | 'print'>('laser')
const cameraModalOpen = ref(false)
const uploadedImagePath = ref<string>()
const DOUBLE_ENTER_INTERVAL_MS = 300
const TRAILING_NEWLINES_REGEX = /[\r\n]+$/
const SEND_MODES = ['enter', 'ctrl-enter', 'double-enter'] as const
type SendMode = (typeof SEND_MODES)[number]
const sendMode = useLocalStorage<SendMode>('ui/chat/settings/send-mode', 'enter')
const lastEnterTime = ref(0)
const STALE_TRANSPORT_ERROR_REGEX = /structuredClone|无法在[“"]Window[”"]上执行/

const providersStore = useProvidersStore()
const { activeProvider, activeModel } = storeToRefs(useConsciousnessStore())
const { stageModelSelected, themeColorsHueDynamic } = storeToRefs(useSettings())
const isYXZExhibition = computed(() => stageModelSelected.value === 'preset-yxz')
const quickStartPrompts = [
  '帮我设计一个校园纪念徽章',
  '我想做一个可爱的桌面摆件',
  '帮我把一个环保创意做成 3D 作品',
] as const

const { askPermission } = useSettingsAudioDevice()
const { selectedAudioInput, audioInputs } = storeToRefs(useSettingsAudioDevice())
const chatOrchestrator = useChatOrchestratorStore()
const chatSession = useChatSessionStore()
const chatStream = useChatStreamStore()
const { cancelPendingSends, ingest, onAfterMessageComposed } = chatOrchestrator
// A turn is in flight: a second tap must not queue another identical turn.
const sendInFlight = ref(false)
const { messages } = storeToRefs(chatSession)
const { t } = useI18n()
const sendModeLabels = computed<Record<SendMode, string>>(() => ({
  'enter': t('stage.send-mode.enter'),
  'ctrl-enter': t('stage.send-mode.ctrl-enter'),
  'double-enter': t('stage.send-mode.double-enter'),
}))

// Speech input pipeline
const hearingStore = useHearingStore()
const { autoSendEnabled, autoSendDelay } = storeToRefs(hearingStore)

// Auto-send logic
let autoSendTimeout: ReturnType<typeof setTimeout> | undefined
const pendingAutoSendText = ref('')

function clearPendingAutoSend() {
  if (autoSendTimeout) {
    clearTimeout(autoSendTimeout)
    autoSendTimeout = undefined
  }
  pendingAutoSendText.value = ''
}

/**
 * Insert recognized speech at the textarea caret (or replace the current
 * selection), falling back to appending at the end when the input is not
 * focused. Keeps the caret right after the inserted text so students can
 * keep talking / continue typing.
 */
function insertTranscriptAtCaret(text: string) {
  const current = messageInput.value
  const el = document.activeElement as HTMLTextAreaElement | null
  if (el && el.tagName === 'TEXTAREA' && typeof el.selectionStart === 'number') {
    const start = el.selectionStart
    const end = el.selectionEnd
    const replacement = start === end ? `${text} ` : text
    messageInput.value = current.slice(0, start) + replacement + current.slice(end)
    nextTick(() => {
      const caret = start + replacement.length
      el.focus()
      el.setSelectionRange(caret, caret)
    })
    return
  }
  const trimmed = current.trim()
  messageInput.value = trimmed ? `${trimmed} ${text}` : text
}

function scheduleAutoSend() {
  if (autoSendTimeout)
    clearTimeout(autoSendTimeout)

  autoSendTimeout = setTimeout(() => {
    autoSendTimeout = undefined
    void runAutoSend()
  }, autoSendDelay.value)
}

async function runAutoSend() {
  if (!autoSendEnabled.value) {
    clearPendingAutoSend()
    return
  }

  // A turn is still running: wait for it instead of queueing a second one.
  if (sendInFlight.value) {
    scheduleAutoSend()
    return
  }

  const textToSend = pendingAutoSendText.value.trim()
  if (!textToSend)
    return

  try {
    messageInput.value = ''
    pendingAutoSendText.value = ''
    await sendMessage(textToSend)
  }
  catch (err) {
    console.error('[ChatArea] Auto-send error:', err)
    messageInput.value = [textToSend, messageInput.value.trim()].filter(Boolean).join(' ')
    pendingAutoSendText.value = [textToSend, pendingAutoSendText.value.trim()].filter(Boolean).join(' ')
    recoverFromSendError(err)
  }
}

// A turn can legitimately take minutes: four preview images plus a 3D model.
// The stall detector must therefore see that the assistant is still working,
// otherwise a slow-but-healthy turn is aborted and the visitor is left
// looking at a chat that never answers.
//
// The stamp carries everything that changes while a turn runs: the streamed
// text, the tool calls, and the messages that land in the conversation.
function chatProgressStamp() {
  const stream = chatStream.streamingMessage
  const sessionMessages = messages.value
  const last = sessionMessages.at(-1)
  const lastContent = last?.content
  // The creation card reports its own progress (preview generated, 3D model
  // at 17%, engine switching) by rewriting the message it lives in, so the
  // card's progress text is part of the fingerprint too.
  const lastCreation = findLastCreationCard()

  return [
    stream?.content?.length ?? 0,
    stream?.slices?.length ?? 0,
    stream?.tool_results?.length ?? 0,
    sessionMessages.length,
    typeof lastContent === 'string' ? lastContent : '',
    lastCreation?.status ?? '',
    lastCreation?.progressMsg ?? '',
    // The raw provider activity: a reasoning model writes nothing while it
    // thinks, and the watchdog has to know that the turn is not dead.
    chatStream.lastActivityAt,
  ].join('|')
}

/**
 * The newest 宜小智 creation card in the conversation.
 *
 * The card is rewritten in place while a build runs, and that card does not
 * have to be the last message: the visitor's confirmation ("就这个，开始生成
 * 3D 模型吧") is appended after it.  Looking at the last message only would
 * therefore miss the progress of a running build -- and the watchdog would
 * mistake a healthy 3D build for a frozen chat.
 */
function findLastCreationCard() {
  const list = messages.value
  for (let index = list.length - 1; index >= 0; index--) {
    const creation = (list[index] as { yxzCreation?: { status?: string, progressMsg?: string } } | undefined)?.yxzCreation
    if (creation)
      return creation
  }
  return undefined
}

/**
 * True while the turn is busy with something that produces no chat text.
 *
 * A tool call (four preview images, a 3D build, a laser card) runs for
 * minutes without a single new character in the conversation.  Treating
 * that silence as a stall is what aborted healthy runs and produced the
 * "请切换一个可用模型" message the visitor saw.
 */
function chatTurnIsBusy() {
  const stream = chatStream.streamingMessage
  const toolCalls = stream?.slices?.filter(slice => slice.type === 'tool-call').length ?? 0
  const toolResults = stream?.tool_results?.length ?? 0
  if (toolCalls > toolResults)
    return true

  // A preview or a build that is running rewrites its card with progress
 // messages.
  const status = findLastCreationCard()?.status
  return status === 'model-building' || status === 'preview-building'
}

async function sendMessage(text: string, providerId?: string, model?: string) {
  if (sendInFlight.value) {
    console.warn('[ChatArea] Send ignored: a turn is already running')
    return
  }

  sendInFlight.value = true
  const pid = providerId ?? activeProvider.value
  try {
    const operation = (async () => {
      const providerConfig = providersStore.getProviderConfig(pid)
      await ingest(text, {
        chatProvider: await providersStore.getProviderInstance(pid) as ChatProvider,
        // A backup channel speaks its own model: sending "MiniMax-M2.7" to
        // DeepSeek (or the other way round) is exactly the "please pick
        // another model" dead end this app is supposed to handle itself.
        model: model || activeModel.value,
        providerConfig,
        providerId: pid,
      })
    })()

    return await withChatSendTimeout(
      operation,
      () => {
        cancelPendingSends(chatSession.activeSessionId)
      },
      chatProgressStamp,
      { isTurnActive: chatTurnIsBusy },
    )
  }
  finally {
    sendInFlight.value = false
  }
}

// One automatic retry per preserved message: a failed turn is retried
// through the next configured chat channel before the recovery toast
// surfaces.  Students should not have to understand provider failures at all.
let lastAutoRetriedText = ''

// The failed turn already appended the visitor's question to the session.
// Drop that copy before a retry so the chat keeps exactly one of it.
function removeTrailingUserMessage(text: string) {
  const sessionId = chatSession.activeSessionId
  const messages = chatSession.getSessionMessages(sessionId)

  const last = messages.at(-1)
  if (!last || last.role !== 'user')
    return

  const content = typeof last.content === 'string' ? last.content : ''
  if (content.trim() !== text.trim())
    return

  chatSession.setSessionMessages(sessionId, messages.slice(0, -1))
}

async function recoverFromSendError(error: unknown) {
  // Keep implementation details in the console only. The conversation should
  // remain readable and actionable for a visitor at the exhibition.
  const timedOut = error instanceof ChatSendTimeoutError
  const retryText = pendingAutoSendText.value.trim() || messageInput.value.trim()

  if (retryText && retryText !== lastAutoRetriedText) {
    // The visitor never picks a model: the app walks the configured backup
    // channels itself.  The explicit fallback list (provider + model) comes
    // first; the remaining chat providers are the last resort.
    const { candidates } = resolveFallbackCandidates({
      providerId: activeProvider.value,
      model: activeModel.value,
      scope: 'consciousness',
    })
    const configuredChat = providersStore.persistedChatProvidersMetadata ?? []
    const backups = [
      ...candidates.map(candidate => ({ providerId: candidate.providerId, model: candidate.model })),
      ...configuredChat
        .filter(meta => meta.id !== activeProvider.value && !candidates.some(candidate => candidate.providerId === meta.id))
        .map(meta => ({ providerId: meta.id, model: '' })),
    ]

    for (const backup of backups) {
      lastAutoRetriedText = retryText
      toast.info('正在换一条可用通道继续…')
      try {
        removeTrailingUserMessage(retryText)
        await sendMessage(retryText, backup.providerId, backup.model || undefined)
        pendingAutoSendText.value = ''
        messageInput.value = ''
        return
      }
      catch (retryError) {
        console.warn('[ChatArea] Backup provider retry failed:', retryError)
      }
    }
  }

  console.error('[ChatArea] Send recovery:', error)
  notifyYXZChatRecovery()
  toast.error(timedOut ? '连接等待时间较长' : '刚才没有连接成功', {
    description: timedOut
      ? '我已经保留你的内容，稍等一下再点发送就能继续。'
      : '我已经保留你的内容，请再试一次。',
  })

  // Remove only stale internal transport cards left by an older session.
  const cleanMessages = messages.value.filter(message => message.role !== 'error' || !STALE_TRANSPORT_ERROR_REGEX.test(message.content))
  if (cleanMessages.length !== messages.value.length)
    chatSession.setSessionMessages(chatSession.activeSessionId, cleanMessages)
}

async function handleSend() {
  if (!messageInput.value.trim() || isComposing.value || sendInFlight.value) {
    return
  }

  const textToSend = messageInput.value
  messageInput.value = ''

  try {
    await sendMessage(textToSend)
  }
  catch (error) {
    messageInput.value = textToSend
    recoverFromSendError(error)
  }
}

async function sendQuickStart(prompt: string) {
  if (messageInput.value.trim() || sendInFlight.value)
    return

  messageInput.value = prompt
  await handleSend()
}

// + menu: open the preset YXZ 3D creation studio (printable models, not the
// animated VRM). The studio shows 3 preset poses and the full edit pipeline.
function openPresetYXZ3D() {
  const url = `${window.location.origin}/yxz-studio`
  window.open(url, '_blank', 'noopener,noreferrer')
}

// + menu: open the guided creation workbench. The laser branch drives the
// full chain (conversation -> preview -> studio -> 3D -> SVG -> xTool) and the
// print branch drives the same chain up to the printable STL.
function openWorkbench(mode: 'laser' | 'print') {
  workbenchMode.value = mode
  workbenchOpen.value = true
}

function handleWorkbenchStatus(status: string) {
  if (status === 'sent')
    workbenchOpen.value = false
}

// Camera capture: handle photo taken from camera
async function handleCameraImage(_imageDataUrl: string, blob: Blob) {
  try {
    // Create form data for upload
    const formData = new FormData()
    formData.append('image', blob, 'camera-capture.jpg')
    formData.append('source', 'camera')

    // Show uploading toast
    const uploadingToast = toast.loading('正在上传照片...')

    // Upload to backend
    const response = await fetch(`${getYXZPrintApiBase()}/api/upload-image`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`上传失败: ${response.statusText}`)
    }

    const result = await response.json()
    uploadedImagePath.value = result.image_path

    // Dismiss uploading toast
    toast.dismiss(uploadingToast)

    // Show success
    toast.success('照片已上传', {
      description: result.description || '可以开始创作了',
    })

    // Auto-fill message input with context
    const description = result.description || '我的照片'
    messageInput.value = `[已上传照片: ${description}] 帮我用这张照片`

    // Close camera modal
    cameraModalOpen.value = false

    // Focus on textarea
    await nextTick()
    const textarea = document.querySelector('textarea')
    if (textarea) {
      textarea.focus()
      // Move cursor to end
      textarea.setSelectionRange(messageInput.value.length, messageInput.value.length)
    }
  }
  catch (error) {
    console.error('照片上传失败:', error)
    toast.error('照片上传失败', {
      description: '请检查网络连接或稍后重试',
    })
  }
}

function sendFromKeyboard() {
  messageInput.value = messageInput.value.replace(TRAILING_NEWLINES_REGEX, '')
  void handleSend()
}

function handleMessageInputKeydown(event: KeyboardEvent) {
  if (isComposing.value || event.key !== 'Enter')
    return

  const hasControl = event.ctrlKey || event.metaKey
  const hasShift = event.shiftKey

  switch (sendMode.value) {
    case 'enter':
      if (!hasShift && !hasControl) {
        event.preventDefault()
        sendFromKeyboard()
      }
      return
    case 'ctrl-enter':
      if (hasControl) {
        event.preventDefault()
        sendFromKeyboard()
      }
      return
    case 'double-enter':
      if (!hasShift && !hasControl) {
        const now = Date.now()
        if (now - lastEnterTime.value < DOUBLE_ENTER_INTERVAL_MS) {
          event.preventDefault()
          sendFromKeyboard()
          lastEnterTime.value = 0
        }
        else {
          lastEnterTime.value = now
        }
      }
  }
}

watch(hearingPopoverOpen, async (value) => {
  if (value) {
    await askPermission()
  }
})

onAfterMessageComposed(async () => {
})

onUnmounted(() => {
  // Clear auto-send timeout on unmount
  if (autoSendTimeout) {
    clearTimeout(autoSendTimeout)
    autoSendTimeout = undefined
  }
})

// --- Voice input -------------------------------------------------------
// The browser only records the clip; the recognition itself runs on the
// machine that serves 宜小智 (see useYXZVoiceInput).  No API key, no
// network, and the same answer on every computer in the room.
const voice = useYXZVoiceInput({
  deviceId: () => selectedAudioInput.value || undefined,
  onText: (text) => {
    // Fill the recognised speech into the input box at the caret.
    insertTranscriptAtCaret(text)
    if (autoSendEnabled.value) {
      pendingAutoSendText.value = text
      scheduleAutoSend()
    }
    else {
      clearPendingAutoSend()
    }
  },
  onError: (description) => {
    toast.error('语音输入失败', { description })
  },
})

const isVoiceRecording = computed(() => voice.state.value === 'recording')
const voiceState = voice.state
const voiceLevel = voice.level
const voiceElapsed = voice.elapsed

async function toggleVoiceRecording() {
  if (voice.state.value === 'recording') {
    await voice.stop()
    return
  }
  if (voice.state.value === 'transcribing')
    return
  await voice.start()
}

// Watch for auto-send setting changes and clear pending sends if disabled
watch(autoSendEnabled, (enabled) => {
  if (!enabled) {
    // Auto-send was disabled - clear any pending auto-send
    clearPendingAutoSend()
    console.info('[ChatArea] Auto-send disabled, cleared pending text')
  }
})

watch(sendMode, () => {
  lastEnterTime.value = 0
})
</script>

<template>
  <div h="<md:full" flex gap-2 class="ph-no-capture">
    <div
      :class="[
        'relative',
        'w-full',
        'bg-primary-200/20 dark:bg-primary-400/20',
      ]"
    >
      <div
        v-if="isYXZExhibition && !messageInput.trim()"
        class="flex flex-wrap gap-1.5 border-b border-primary-200/30 px-3 pb-2 pt-2"
        aria-label="宜小智体验示例"
      >
        <span class="w-full text-xs text-primary-600/75 dark:text-primary-200/80">不知道怎么开始？选一个创作方向：</span>
        <button
          v-for="prompt in quickStartPrompts"
          :key="prompt"
          type="button"
          :disabled="sendInFlight"
          class="border border-primary-300/50 rounded-full bg-white/80 px-2.5 py-1 text-xs text-primary-700 shadow-sm backdrop-blur transition active:scale-95 disabled:cursor-not-allowed dark:border-primary-500/40 dark:bg-neutral-900/70 hover:bg-white dark:text-primary-200 disabled:opacity-45"
          @click="void sendQuickStart(prompt)"
        >
          {{ prompt }}
        </button>
        <span
          v-if="sendInFlight"
          class="w-full text-xs text-primary-600/75 dark:text-primary-200/80"
        >
          宜小智正在思考，请稍候…
        </span>
      </div>

      <!-- Uploaded photo chip: the camera capture result that the agent can use -->
      <div
        v-if="uploadedImagePath"
        class="flex items-center gap-2 border-b border-primary-200/30 px-3 py-2"
      >
        <img
          :src="`${getYXZPrintApiBase()}${uploadedImagePath}`"
          alt="已上传的照片"
          class="h-10 w-10 shrink-0 border border-primary-200/60 rounded-lg object-cover"
        >
        <span class="min-w-0 flex-1 truncate text-xs text-neutral-500 dark:text-neutral-400">
          照片已上传，可以补充你的创作想法
        </span>
        <button
          type="button"
          class="shrink-0 rounded-md px-2 py-1 text-xs text-neutral-400 transition hover:bg-neutral-100 dark:hover:bg-neutral-800"
          @click="uploadedImagePath = undefined"
        >
          移除
        </button>
      </div>

      <BasicTextarea
        v-model="messageInput"
        :submit-on-enter="false"
        :placeholder="t('stage.message')"
        text="primary-600 dark:primary-100  placeholder:primary-500 dark:placeholder:primary-200"
        bg="transparent"
        min-h="[100px]" max-h="[300px]" w-full
        rounded-t-xl p-4 font-medium pb="[60px]"
        outline-none transition="all duration-250 ease-in-out placeholder:all placeholder:duration-250 placeholder:ease-in-out"
        :class="{
          'transition-colors-none placeholder:transition-colors-none': themeColorsHueDynamic,
        }"
        @keydown="handleMessageInputKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
      />

      <!-- Bottom-left action buttons: Create (+) / Send mode / Microphone -->
      <div
        absolute bottom-2 left-2 z-10 flex items-center gap-2
      >
        <!-- Create menu: laser-cut business card -->
        <DropdownMenuRoot>
          <DropdownMenuTrigger as-child>
            <button
              :class="[
                'h-8 w-8 flex items-center justify-center rounded-md outline-none transition-all duration-200 active:scale-95',
                'text-lg text-neutral-500 dark:text-neutral-400',
              ]"
              title="创建"
              aria-label="创建"
            >
              <div class="i-ph:plus-bold h-5 w-5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent
              side="top"
              align="start"
              :side-offset="8"
              :class="[
                'z-50 min-w-[220px] rounded-xl border border-neutral-200/60 bg-neutral-50/90 p-1',
                'shadow-lg backdrop-blur-md dark:border-neutral-800/30 dark:bg-neutral-900/80',
                'flex flex-col gap-1',
              ]"
            >
              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="openWorkbench('laser')"
              >
                <div class="i-ph:cardholder-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>激光切割卡片</span>
                <small class="text-neutral-400">对话引导 · 作品正面 · SVG 切割</small>
              </DropdownMenuItem>
              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="openWorkbench('print')"
              >
                <div class="i-ph:robot-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>3D 打印作品</span>
                <small class="text-neutral-400">对话引导 · 预览 · 3D 打印</small>
              </DropdownMenuItem>
              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="openPresetYXZ3D"
              >
                <div class="i-ph:hammer-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>创作工作室</span>
                <small class="text-neutral-400">2D 批注编辑 · 产出 3D</small>
              </DropdownMenuItem>
              <DropdownMenuItem
                class="w-full flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs outline-none transition-colors hover:bg-primary-100/60 dark:hover:bg-primary-900/40"
                @select="cameraModalOpen = true"
              >
                <div class="i-ph:camera-bold h-4 w-4 text-primary-600 dark:text-primary-300" />
                <span>拍照创作</span>
                <small class="text-neutral-400">摄像头拍摄 · AI 识图 · 引导创作</small>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>

        <DropdownMenuRoot>
          <DropdownMenuTrigger as-child>
            <button
              :class="[
                'h-8 w-8 flex items-center justify-center rounded-md outline-none transition-all duration-200 active:scale-95',
                'text-lg text-neutral-500 dark:text-neutral-400',
              ]"
              :title="t('stage.send-mode.title')"
            >
              <div class="i-solar:keyboard-bold-duotone h-5 w-5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent
              side="top"
              align="start"
              :side-offset="8"
              :class="[
                'z-50 min-w-[180px] rounded-xl border border-neutral-200/60 bg-neutral-50/90 p-1',
                'shadow-lg backdrop-blur-md dark:border-neutral-800/30 dark:bg-neutral-900/80',
                'flex flex-col gap-1',
              ]"
            >
              <DropdownMenuItem
                v-for="mode in SEND_MODES"
                :key="mode"
                :class="[
                  'w-full flex cursor-pointer items-center rounded-lg px-3 py-2 text-xs outline-none transition-colors',
                  'hover:bg-primary-100/60 dark:hover:bg-primary-900/40',
                  sendMode === mode ? 'bg-primary-100/60 text-primary-600 font-medium dark:bg-primary-900/40 dark:text-primary-300' : 'text-neutral-600 dark:text-neutral-300',
                ]"
                @select="sendMode = mode"
              >
                <div class="mr-2 h-4 w-4 flex items-center justify-center">
                  <div v-if="sendMode === mode" class="i-ph:check-bold h-4 w-4" />
                </div>
                <span>{{ sendModeLabels[mode] }}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenuRoot>

        <!-- Voice input: one click to record, one click to send it off -->
        <button
          :class="[
            'h-8 w-8 flex items-center justify-center rounded-md outline-none',
            'transition-all duration-200 active:scale-95',
            isVoiceRecording ? 'text-rose-500 dark:text-rose-400' : 'text-neutral-500 dark:text-neutral-400',
          ]"
          :title="isVoiceRecording ? `正在录音 ${voiceElapsed.toFixed(0)} 秒，点击结束` : '语音输入'"
          :aria-label="isVoiceRecording ? '结束录音' : '开始录音'"
          :disabled="voiceState === 'transcribing'"
          @click="void toggleVoiceRecording()"
        >
          <span
            v-if="isVoiceRecording"
            class="relative grid h-5 w-5 place-items-center"
          >
            <span
              class="absolute inset-0 rounded-full bg-rose-500/25"
              :style="{ transform: `scale(${1 + voiceLevel * 0.6})`, opacity: String(0.35 + voiceLevel * 0.5) }"
            />
            <span class="h-2.5 w-2.5 rounded-[3px] bg-rose-500" />
          </span>
          <div v-else-if="voiceState === 'transcribing'" class="i-solar:loading-animation-linear h-5 w-5" />
          <div v-else class="i-ph:microphone h-5 w-5" />
        </button>

        <!-- Microphone picker -->
        <PopoverRoot v-model:open="hearingPopoverOpen">
          <PopoverTrigger as-child>
            <button
              :class="[
                'h-8 w-8 flex items-center justify-center rounded-md outline-none',
                'transition-all duration-200 active:scale-95',
              ]"
              text="lg neutral-500 dark:neutral-400"
              title="选择麦克风"
              aria-label="选择麦克风"
            >
              <div class="i-ph:sliders-horizontal h-5 w-5" />
            </button>
          </PopoverTrigger>
          <PopoverContent
            side="top"
            :side-offset="8"
            :class="[
              'w-72 max-w-[18rem] rounded-xl border border-neutral-200/60 bg-neutral-50/90 p-4',
              'shadow-lg backdrop-blur-md dark:border-neutral-800/30 dark:bg-neutral-900/80',
              'flex flex-col gap-3',
            ]"
          >
            <FieldCombobox
              v-model="selectedAudioInput"
              label="Input device"
              description="Select the microphone you want to use."
              :options="audioInputs.map(device => ({ label: device.label || 'Unknown Device', value: device.deviceId }))"
              layout="vertical"
              placeholder="Select microphone"
            />
            <p class="text-xs text-neutral-500 dark:text-neutral-400">
              语音识别在本机完成，无需联网，也不会消耗任何额度。
            </p>
          </PopoverContent>
        </PopoverRoot>
      </div>
    </div>

    <YXZCreationWorkbench
      v-model:open="workbenchOpen"
      :mode="workbenchMode"
      @status="handleWorkbenchStatus"
    />

    <!-- Camera capture modal: shoot a photo, then let the agent guide the creation -->
    <div
      v-if="cameraModalOpen"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      @click.self="cameraModalOpen = false"
    >
      <div class="max-h-[90vh] max-w-2xl w-full overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl dark:bg-neutral-900">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-sm text-neutral-800 font-medium dark:text-neutral-100">
            拍照创作
          </h3>
          <button
            type="button"
            class="rounded-md px-2 py-1 text-xs text-neutral-400 transition hover:bg-neutral-100 dark:hover:bg-neutral-800"
            @click="cameraModalOpen = false"
          >
            关闭
          </button>
        </div>
        <CameraCapture
          @confirm="handleCameraImage"
          @cancel="cameraModalOpen = false"
        />
      </div>
    </div>
  </div>
</template>
