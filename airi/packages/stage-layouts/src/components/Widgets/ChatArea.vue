<script setup lang="ts">
import type { ChatProvider } from '@xsai-ext/providers/utils'

import { isStageTamagotchi } from '@proj-airi/stage-shared'
import { YXZCreationWorkbench } from '@proj-airi/stage-ui/components/scenes'
import { useAudioAnalyzer } from '@proj-airi/stage-ui/composables'
import { getYXZPrintApiBase } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'
import { useAudioContext } from '@proj-airi/stage-ui/stores/audio'
import { useChatOrchestratorStore } from '@proj-airi/stage-ui/stores/chat'
import { useChatSessionStore } from '@proj-airi/stage-ui/stores/chat/session-store'
import { useChatStreamStore } from '@proj-airi/stage-ui/stores/chat/stream-store'
import { useConsciousnessStore } from '@proj-airi/stage-ui/stores/modules/consciousness'
import { useHearingSpeechInputPipeline, useHearingStore } from '@proj-airi/stage-ui/stores/modules/hearing'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { BasicTextarea, FieldCombobox } from '@proj-airi/ui'
import { until, useLocalStorage } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { DropdownMenuContent, DropdownMenuItem, DropdownMenuPortal, DropdownMenuRoot, DropdownMenuTrigger, PopoverContent, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'

import CameraCapture from './CameraCapture.vue'
import IndicatorMicVolume from './IndicatorMicVolume.vue'

import { ChatSendTimeoutError, notifyYXZChatRecovery, withChatSendTimeout } from './chat-send-recovery'

const messageInput = ref('')
const hearingPopoverOpen = ref(false)
const isComposing = ref(false)
const isListening = ref(false) // Transcription listening state (separate from microphone enabled)
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

const { askPermission, startStream } = useSettingsAudioDevice()
const { enabled, selectedAudioInput, stream, audioInputs } = storeToRefs(useSettingsAudioDevice())
const chatOrchestrator = useChatOrchestratorStore()
const chatSession = useChatSessionStore()
const chatStream = useChatStreamStore()
const { cancelPendingSends, ingest, onAfterMessageComposed } = chatOrchestrator
// A turn is in flight: a second tap must not queue another identical turn.
const sendInFlight = ref(false)
const { messages } = storeToRefs(chatSession)
const { audioContext } = useAudioContext()
const { t } = useI18n()
const sendModeLabels = computed<Record<SendMode, string>>(() => ({
  'enter': t('stage.send-mode.enter'),
  'ctrl-enter': t('stage.send-mode.ctrl-enter'),
  'double-enter': t('stage.send-mode.double-enter'),
}))

// Transcription pipeline
const hearingStore = useHearingStore()
const hearingPipeline = useHearingSpeechInputPipeline()
const { transcribeForMediaStream, stopStreamingTranscription } = hearingPipeline
const { supportsStreamInput } = storeToRefs(hearingPipeline)
const { configured: hearingConfigured, autoSendEnabled, autoSendDelay } = storeToRefs(hearingStore)
const shouldUseStreamInput = computed(() => supportsStreamInput.value && !!stream.value)

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

// --- Live interim transcription ---
// While the user is still speaking, interim text is shown at the caret right
// away. When the sentence is finalised it replaces the placeholder instead of
// being appended again, so the box never duplicates or lags.
const interimPlaceholder = ref<{ anchor: number, length: number } | null>(null)

function insertInterimAtCaret(text: string) {
  const current = messageInput.value
  const el = document.activeElement as HTMLTextAreaElement | null
  const editable = el && el.tagName === 'TEXTAREA' && typeof el.selectionStart === 'number'
  if (!editable) {
    // No focused textarea: append plainly (no placeholder tracking).
    const trimmed = current.trim()
    messageInput.value = trimmed ? `${trimmed} ${text}` : text
    return
  }
  if (interimPlaceholder.value) {
    const { anchor, length } = interimPlaceholder.value
    messageInput.value = current.slice(0, anchor) + text + current.slice(anchor + length)
    interimPlaceholder.value = { anchor, length: text.length }
  }
  else {
    const start = el.selectionStart
    const end = el.selectionEnd
    const replacement = start === end ? text : text
    messageInput.value = current.slice(0, start) + replacement + current.slice(end)
    interimPlaceholder.value = { anchor: start, length: replacement.length }
  }
  nextTick(() => {
    if (!interimPlaceholder.value)
      return
    const caret = interimPlaceholder.value.anchor + interimPlaceholder.value.length
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

function commitInterimAsFinal(text: string) {
  const el = document.activeElement as HTMLTextAreaElement | null
  if (interimPlaceholder.value && el && el.tagName === 'TEXTAREA') {
    const { anchor, length } = interimPlaceholder.value
    const current = messageInput.value
    messageInput.value = current.slice(0, anchor) + text + current.slice(anchor + length)
    nextTick(() => {
      el.focus()
      el.setSelectionRange(anchor + text.length, anchor + text.length)
    })
    interimPlaceholder.value = null
    return
  }
  interimPlaceholder.value = null
  insertTranscriptAtCaret(text)
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

function debouncedAutoSend(text: string) {
  if (!autoSendEnabled.value) {
    clearPendingAutoSend()
    return
  }

  pendingAutoSendText.value = pendingAutoSendText.value ? `${pendingAutoSendText.value} ${text}` : text

  scheduleAutoSend()
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
  const lastCreation = (last as { yxzCreation?: { status?: string, progressMsg?: string } } | undefined)?.yxzCreation

  return [
    stream?.content?.length ?? 0,
    stream?.slices?.length ?? 0,
    stream?.tool_results?.length ?? 0,
    sessionMessages.length,
    typeof lastContent === 'string' ? lastContent : '',
    lastCreation?.status ?? '',
    lastCreation?.progressMsg ?? '',
  ].join('|')
}

async function sendMessage(text: string, providerId?: string) {
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
        model: activeModel.value,
        providerConfig,
        providerId: pid,
      })
    })()

    return await withChatSendTimeout(operation, () => {
      cancelPendingSends(chatSession.activeSessionId)
    }, chatProgressStamp)
  }
  finally {
    sendInFlight.value = false
  }
}

// One automatic retry per preserved message: a non-timeout failure is retried
// once through a backup chat provider before the recovery toast surfaces.
// Students should not have to understand provider failures at all.
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

  if (!timedOut && retryText && retryText !== lastAutoRetriedText) {
    // Only a provider the visitor (or the local seed) actually added may take
    // over: the connectivity validator accepts any HTTP status below 500, so
    // untouched providers would otherwise answer with 401 and fail the retry.
    const configuredChat = providersStore.persistedChatProvidersMetadata ?? []
    const backup = configuredChat.find(meta => meta.id !== activeProvider.value)
    if (backup) {
      lastAutoRetriedText = retryText
      toast.info(`自动切换到备用模型重试…`)
      try {
        removeTrailingUserMessage(retryText)
        await sendMessage(retryText, backup.id)
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
      ? '我已经保留你的内容，请稍后重试或切换一个可用模型。'
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

const { startAnalyzer, stopAnalyzer, volumeLevel } = useAudioAnalyzer()
const normalizedVolume = computed(() => Math.min(1, Math.max(0, (volumeLevel.value ?? 0) / 100)))
let analyzerSource: MediaStreamAudioSourceNode | undefined

function teardownAnalyzer() {
  try {
    analyzerSource?.disconnect()
  }
  catch {}
  analyzerSource = undefined
  stopAnalyzer()
}

async function setupAnalyzer() {
  teardownAnalyzer()
  if (!hearingPopoverOpen.value || !enabled.value || !stream.value)
    return
  if (audioContext.state === 'suspended')
    await audioContext.resume()
  const analyser = startAnalyzer(audioContext)
  if (!analyser)
    return
  analyzerSource = audioContext.createMediaStreamSource(stream.value)
  analyzerSource.connect(analyser)
}

watch([hearingPopoverOpen, enabled, stream], () => {
  setupAnalyzer()
}, { immediate: true })

onUnmounted(() => {
  teardownAnalyzer()
  stopListening()

  // Clear auto-send timeout on unmount
  if (autoSendTimeout) {
    clearTimeout(autoSendTimeout)
    autoSendTimeout = undefined
  }
})

// Transcription listening functions
async function startListening() {
  // Allow calling this even if already listening - transcribeForMediaStream will handle session reuse/restart
  try {
    console.info('[ChatArea] Starting listening...', {
      enabled: enabled.value,
      hasStream: !!stream.value,
      supportsStreamInput: supportsStreamInput.value,
      hearingConfigured: hearingConfigured.value,
    })

    // Auto-configure Web Speech API as default if no provider is configured
    if (!hearingConfigured.value) {
      // Check if Web Speech API is available in the browser
      // Web Speech API is NOT available in Electron (stage-tamagotchi) - it requires Google's embedded API keys
      // which are not available in Electron, causing it to fail at runtime
      const isWebSpeechAvailable = typeof window !== 'undefined'
        && !isStageTamagotchi() // Explicitly exclude Electron
        && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)

      if (isWebSpeechAvailable) {
        console.info('[ChatArea] No transcription provider configured. Auto-configuring Web Speech API as default...')

        // Initialize the provider in the providers store first
        try {
          providersStore.initializeProvider('browser-web-speech-api')
        }
        catch (err) {
          console.warn('[ChatArea] Error initializing Web Speech API provider:', err)
        }

        // Set as active provider
        hearingStore.activeTranscriptionProvider = 'browser-web-speech-api'

        // Wait for reactivity to update
        await nextTick()

        // Verify the provider was set correctly
        if (hearingStore.activeTranscriptionProvider === 'browser-web-speech-api') {
          console.info('[ChatArea] Web Speech API configured as default provider')
          // Continue with transcription - Web Speech API is ready
        }
        else {
          console.error('[ChatArea] Failed to set Web Speech API as default provider')
          isListening.value = false
          return
        }
      }
      else {
        console.error('[ChatArea] Web Speech API not available. No transcription provider configured and Web Speech API is not available in this browser. Please go to Settings > Modules > Hearing to configure a transcription provider. Browser support:', {
          hasWindow: typeof window !== 'undefined',
          hasWebkitSpeechRecognition: typeof window !== 'undefined' && 'webkitSpeechRecognition' in window,
          hasSpeechRecognition: typeof window !== 'undefined' && 'SpeechRecognition' in window,
        })
        isListening.value = false
        toast.error('语音输入不可用', {
          description: '当前浏览器不支持语音识别，请使用 Chrome 或 Edge 浏览器（或检查浏览器设置中的麦克风权限）。',
        })
        return
      }
    }

    // Request microphone permission if needed (microphone should already be enabled by the user)
    if (!stream.value) {
      console.info('[ChatArea] Requesting microphone permission...')
      await askPermission()

      // If still no stream, try starting it manually
      if (!stream.value && enabled.value) {
        console.info('[ChatArea] Attempting to start stream manually...')
        startStream()
        // Wait for the stream to become available with a timeout.
        try {
          await until(stream).toBeTruthy({ timeout: 3000, throwOnTimeout: true })
        }
        catch {
          console.error('[ChatArea] Timed out waiting for audio stream.')
          isListening.value = false
          toast.error('麦克风启动超时', {
            description: '请在浏览器地址栏左侧允许麦克风权限后重试。',
          })
          return
        }
      }
    }

    if (!stream.value) {
      const errorMsg = 'Failed to get audio stream for transcription. Please check microphone permissions and ensure a device is selected.'
      console.error('[ChatArea]', errorMsg)
      isListening.value = false
      toast.error('无法使用麦克风', {
        description: '请点击浏览器地址栏的麦克风图标，允许本页使用麦克风，再重试。',
      })
      return
    }

    // Check if streaming input is supported
    if (!shouldUseStreamInput.value) {
      const errorMsg = 'Streaming input not supported by the selected transcription provider. Please select a provider that supports streaming (e.g., Web Speech API).'
      console.warn('[ChatArea]', errorMsg)
      // Clean up any existing sessions from other pages (e.g., test page) that might interfere
      await stopStreamingTranscription(true)
      isListening.value = false
      toast.error('语音识别服务未就绪', {
        description: '请尝试刷新页面后重试；仍不行时在 Chrome/Edge 浏览器中使用。',
      })
      return
    }

    console.info('[ChatArea] Starting streaming transcription with stream:', stream.value.id)

    // Call transcribeForMediaStream - it's async so we await it
    // Set listening state AFTER successful call
    try {
      await transcribeForMediaStream(stream.value, {
        onInterim: (text: string) => {
          if (text && text.trim()) {
            insertInterimAtCaret(text)
          }
        },
        onSentenceEnd: (delta) => {
          if (delta && delta.trim()) {
            // Insert recognized speech at the caret position (fill into the
            // input box), never auto-send unless the user enabled auto-send.
            commitInterimAsFinal(delta)
            console.info('[ChatArea] Received transcription delta:', delta)

            // Auto-send if enabled - check the current value (not captured in closure)
            // This ensures we always respect the current setting, even if callbacks are reused
            if (autoSendEnabled.value) {
              debouncedAutoSend(delta)
            }
            else {
              // If auto-send is disabled, clear any pending auto-send text to prevent accidental sends
              clearPendingAutoSend()
            }
          }
        },
        // Omit onSpeechEnd to avoid re-adding user-deleted text; use sentence deltas only.
      })

      // Only set listening to true if transcription started successfully
      // (transcribeForMediaStream might return early if session already exists)
      isListening.value = true
      console.info('[ChatArea] Streaming transcription initiated successfully')
    }
    catch (err) {
      console.error('[ChatArea] Transcription error:', err)
      isListening.value = false
      throw err // Re-throw to be caught by outer catch
    }
  }
  catch (err) {
    console.error('[ChatArea] Failed to start transcription:', err)
    isListening.value = false
    toast.error('语音识别启动失败', {
      description: '请检查麦克风权限与设备选择后重试。',
    })
  }
}

async function stopListening() {
  if (!isListening.value)
    return

  try {
    console.info('[ChatArea] Stopping transcription...')

    // Clear auto-send timeout
    clearPendingAutoSend()

    // Send any pending text immediately if auto-send is enabled
    if (autoSendEnabled.value && pendingAutoSendText.value.trim()) {
      const textToSend = pendingAutoSendText.value.trim()
      pendingAutoSendText.value = ''
      try {
        await sendMessage(textToSend)
        messageInput.value = ''
      }
      catch (err) {
        console.error('[ChatArea] Auto-send error on stop:', err)
        messageInput.value = [textToSend, messageInput.value.trim()].filter(Boolean).join(' ')
        recoverFromSendError(err)
      }
    }

    await stopStreamingTranscription(true)
    isListening.value = false
    console.info('[ChatArea] Transcription stopped')
  }
  catch (err) {
    console.error('[ChatArea] Error stopping transcription:', err)
    isListening.value = false
  }
}

// Start listening when microphone is enabled and stream is available
watch(enabled, async (val) => {
  if (val && stream.value) {
    // Microphone was just enabled and we have a stream, start transcription
    await startListening()
  }
  else if (!val && isListening.value) {
    // Microphone was disabled, stop transcription
    await stopListening()
  }
})

// Start listening when stream becomes available (if microphone is enabled)
watch(stream, async (val) => {
  if (val && enabled.value && !isListening.value) {
    // Stream became available and microphone is enabled, start transcription
    await startListening()
  }
  else if (!val && isListening.value) {
    // Stream was lost, stop transcription
    await stopListening()
  }
})

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

        <!-- Microphone icon button -->
        <PopoverRoot v-model:open="hearingPopoverOpen">
          <PopoverTrigger as-child>
            <button
              :class="[
                'h-8 w-8 flex items-center justify-center rounded-md outline-none',
                'transition-all duration-200 active:scale-95',
              ]"
              text="lg neutral-500 dark:neutral-400"
              :title="t('settings.hearing.title')"
            >
              <Transition name="fade" mode="out-in">
                <IndicatorMicVolume v-if="enabled" class="h-5 w-5" />
                <div v-else class="i-ph:microphone-slash h-5 w-5" />
              </Transition>
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
            <div class="flex flex-col items-center justify-center">
              <div class="relative h-28 w-28 select-none">
                <div
                  class="absolute left-1/2 top-1/2 h-20 w-20 rounded-full transition-all duration-150 -translate-x-1/2 -translate-y-1/2"
                  :style="{ transform: `translate(-50%, -50%) scale(${1 + normalizedVolume * 0.35})`, opacity: String(0.25 + normalizedVolume * 0.25) }"
                  :class="enabled ? 'bg-primary-500/15 dark:bg-primary-600/20' : 'bg-neutral-300/20 dark:bg-neutral-700/20'"
                />
                <div
                  class="absolute left-1/2 top-1/2 h-24 w-24 rounded-full transition-all duration-200 -translate-x-1/2 -translate-y-1/2"
                  :style="{ transform: `translate(-50%, -50%) scale(${1.2 + normalizedVolume * 0.55})`, opacity: String(0.15 + normalizedVolume * 0.2) }"
                  :class="enabled ? 'bg-primary-500/10 dark:bg-primary-600/15' : 'bg-neutral-300/10 dark:bg-neutral-700/10'"
                />
                <div
                  class="absolute left-1/2 top-1/2 h-28 w-28 rounded-full transition-all duration-300 -translate-x-1/2 -translate-y-1/2"
                  :style="{ transform: `translate(-50%, -50%) scale(${1.5 + normalizedVolume * 0.8})`, opacity: String(0.08 + normalizedVolume * 0.15) }"
                  :class="enabled ? 'bg-primary-500/5 dark:bg-primary-600/10' : 'bg-neutral-300/5 dark:bg-neutral-700/5'"
                />
                <button
                  class="absolute left-1/2 top-1/2 grid h-16 w-16 place-items-center rounded-full shadow-md outline-none transition-all duration-200 -translate-x-1/2 -translate-y-1/2"
                  :class="enabled
                    ? 'bg-primary-500 text-white hover:bg-primary-600 active:scale-95'
                    : 'bg-neutral-200 text-neutral-600 hover:bg-neutral-300 active:scale-95 dark:bg-neutral-700 dark:text-neutral-200'"
                  @click="enabled = !enabled"
                >
                  <div :class="enabled ? 'i-ph:microphone' : 'i-ph:microphone-slash'" class="h-6 w-6" />
                </button>
              </div>
              <p class="mt-3 text-xs text-neutral-500 dark:text-neutral-400">
                {{ enabled ? 'Microphone enabled' : 'Microphone disabled' }}
              </p>
            </div>

            <FieldCombobox
              v-model="selectedAudioInput"
              label="Input device"
              description="Select the microphone you want to use."
              :options="audioInputs.map(device => ({ label: device.label || 'Unknown Device', value: device.deviceId }))"
              layout="vertical"
              placeholder="Select microphone"
            />
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
