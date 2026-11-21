<script setup lang="ts">
import type { ChatHistoryItem } from '@proj-airi/stage-ui/types/chat'
import type { ChatProvider } from '@xsai-ext/providers/utils'

import { ChatHistory, HearingConfigDialog } from '@proj-airi/stage-ui/components'
import { useAudioAnalyzer } from '@proj-airi/stage-ui/composables'
import { useAudioContext } from '@proj-airi/stage-ui/stores/audio'
import { getYXZPrintApiBase } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'
import { useYXZRequirementMemory } from '@proj-airi/stage-ui/composables/use-yxz-requirement-memory'
import { useChatOrchestratorStore } from '@proj-airi/stage-ui/stores/chat'
import { useChatMaintenanceStore } from '@proj-airi/stage-ui/stores/chat/maintenance'
import { useChatSessionStore } from '@proj-airi/stage-ui/stores/chat/session-store'
import { useChatStreamStore } from '@proj-airi/stage-ui/stores/chat/stream-store'
import { useConsciousnessStore } from '@proj-airi/stage-ui/stores/modules/consciousness'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { useSettings, useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { BasicTextarea, useTheme } from '@proj-airi/ui'
import { useResizeObserver, useScreenSafeArea } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

import IndicatorMicVolume from '../Widgets/IndicatorMicVolume.vue'
import { useYXZChatTurnGuard } from '../Widgets/use-yxz-chat-turn-guard'
import ActionAbout from './InteractiveArea/Actions/About.vue'
import ActionViewControls from './InteractiveArea/Actions/ViewControls.vue'
import ViewControlInputs from './ViewControls/Inputs.vue'

import { BackgroundDialogPicker } from '../Backgrounds'
import { ChatSendTimeoutError, notifyYXZChatRecovery, withChatSendTimeout } from '../Widgets/chat-send-recovery'

const { isDark, toggleDark } = useTheme()
const hearingDialogOpen = ref(false)
// The picture the visitor uploaded, remembered as the shape reference for
// the next creation round.  The wide layout has had this for a while; on a
// phone or a tablet the visitor has to be able to do the same thing, and
// that is exactly the device people hand their phone to at an exhibition.
const uploadedImagePath = ref<string>()
const imageFileInput = ref<HTMLInputElement>()
const requirementMemory = useYXZRequirementMemory()
const chatOrchestrator = useChatOrchestratorStore()
const chatSession = useChatSessionStore()
const chatStream = useChatStreamStore()
const { cleanupMessages } = useChatMaintenanceStore()
const { chatProgressStamp, chatTurnIsBusy } = useYXZChatTurnGuard()
const { messages } = storeToRefs(chatSession)
const { streamingMessage } = storeToRefs(chatStream)
const { sending } = storeToRefs(chatOrchestrator)
const { stageModelSelected: settingsStageModelSelected } = storeToRefs(useSettings())
const historyMessages = computed(() => messages.value as unknown as ChatHistoryItem[])
const assistantLabel = computed(() => settingsStageModelSelected.value === 'preset-yxz' ? '宜小智' : undefined)

function handleDeleteMessage(index: number) {
  messages.value = messages.value.filter((_, messageIndex) => messageIndex !== index)
}

const viewControlsActiveMode = ref<'x' | 'y' | 'z' | 'scale'>('scale')
const viewControlsInputsRef = useTemplateRef<InstanceType<typeof ViewControlInputs>>('viewControlsInputs')

const messageInput = ref('')
const isComposing = ref(false)
const backgroundDialogOpen = ref(false)

const screenSafeArea = useScreenSafeArea()
const providersStore = useProvidersStore()
const { activeProvider, activeModel } = storeToRefs(useConsciousnessStore())

useResizeObserver(document.documentElement, () => screenSafeArea.update())
const { themeColorsHueDynamic, stageViewControlsEnabled } = storeToRefs(useSettings())
const settingsAudioDevice = useSettingsAudioDevice()
const { enabled, selectedAudioInput, stream, audioInputs } = storeToRefs(settingsAudioDevice)
const { cancelPendingSends, ingest, onAfterMessageComposed } = chatOrchestrator
const { t } = useI18n()
const { audioContext } = useAudioContext()
const { startAnalyzer, stopAnalyzer, volumeLevel } = useAudioAnalyzer()
let analyzerSource: MediaStreamAudioSourceNode | undefined

function isMobileDevice() {
  // eslint-disable-next-line e18e/prefer-static-regex
  return /Mobi|Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
}

async function handleSubmit() {
  if (!isMobileDevice()) {
    await handleSend()
  }
}

async function handleSend() {
  if (!messageInput.value.trim() || isComposing.value) {
    return
  }

  const textToSend = messageInput.value
  messageInput.value = ''

  try {
    const operation = (async () => {
      const providerConfig = providersStore.getProviderConfig(activeProvider.value)
      await ingest(textToSend, {
        chatProvider: await providersStore.getProviderInstance(activeProvider.value) as ChatProvider,
        model: activeModel.value,
        providerConfig,
      })
    })()
    // The stall detector has to see that the turn is still working.  Without
    // this, a turn that renders four preview images (or a 3D model) looked
    // "stuck" after 90 seconds on a phone, and the running tool was
    // aborted -- the backend kept going and finished, but the visitor was
    // told the preview had failed.
    await withChatSendTimeout(
      operation,
      () => cancelPendingSends(chatSession.activeSessionId),
      chatProgressStamp,
      { isTurnActive: chatTurnIsBusy },
    )
  }
  catch (error) {
    messageInput.value = textToSend
    notifyYXZChatRecovery()
    toast.error(error instanceof ChatSendTimeoutError ? '连接等待时间较长' : '刚才没有连接成功', {
      description: '我已经保留你的内容，请再试一次。',
    })
    console.error('[MobileInteractiveArea] Send recovery:', error)
  }
}

function teardownAnalyzer() {
  try {
    analyzerSource?.disconnect()
  }
  catch {}
  analyzerSource = undefined
  stopAnalyzer()
}

/**
 * Upload a picture and remember it as the shape reference for the next
 * creation round.
 *
 * Whatever the visitor already typed travels along with the picture so the
 * vision model reads the image *together with* the request ("this cat, but
 * as a lamp") instead of captioning it in isolation.
 */
async function uploadImageBlob(blob: Blob, filename: string, source: 'camera' | 'picker') {
  const wish = messageInput.value.trim()
  const formData = new FormData()
  formData.append('image', blob, filename)
  formData.append('source', source)
  formData.append('prompt', wish)

  const uploadingToast = toast.loading('正在上传图片...')

  try {
    const response = await fetch(`${getYXZPrintApiBase()}/api/upload-image`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      let detail = `上传失败（${response.status}）`
      try {
        const raw = await response.json()
        if (raw && typeof raw.detail === 'string' && raw.detail)
          detail = raw.detail
      }
      catch {
        // Keep the generic message.
      }
      throw new Error(detail)
    }

    const result = await response.json()
    uploadedImagePath.value = result.image_path

    requirementMemory.update({
      referenceImage: {
        sessionId: result.session_id,
        path: result.image_path,
        description: result.description || '',
        width: result.width,
        height: result.height,
        // The picture belongs to this conversation only; a picture from an
        // earlier chat must not become the shape reference of a new request.
        chatSessionId: chatSession.activeSessionId,
      },
    })

    toast.dismiss(uploadingToast)
    toast.success('图片已上传', {
      description: result.description || '可以开始创作了',
    })

    const description = result.description || '这张图片'
    const existing = messageInput.value.trim()
    messageInput.value = existing
      ? `[参考图片: ${description}] ${existing}`
      : `[参考图片: ${description}] 帮我把这张图做成一个可以3D打印的作品`
  }
  catch (error) {
    toast.dismiss(uploadingToast)
    console.error('图片上传失败:', error)
    toast.error('图片上传失败', {
      description: error instanceof Error ? error.message : '请检查网络连接或稍后重试',
    })
  }
}

function handleImageFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // Allow picking the very same file again.
  input.value = ''
  if (!file)
    return
  if (!file.type.startsWith('image/')) {
    toast.error('只能上传图片文件')
    return
  }
  void uploadImageBlob(file, file.name || 'upload.png', 'picker')
}

function openImagePicker() {
  imageFileInput.value?.click()
}

function removeUploadedImage() {
  uploadedImagePath.value = undefined
  requirementMemory.update({ referenceImage: null })
}

async function setupAnalyzer() {
  teardownAnalyzer()
  if (!hearingDialogOpen.value || !enabled.value || !stream.value)
    return
  if (audioContext.state === 'suspended')
    await audioContext.resume()
  const analyser = startAnalyzer(audioContext)
  if (!analyser)
    return
  analyzerSource = audioContext.createMediaStreamSource(stream.value)
  analyzerSource.connect(analyser)
}

watch([hearingDialogOpen, enabled, stream], () => {
  setupAnalyzer()
}, { immediate: true })

watch(hearingDialogOpen, (value) => {
  if (value) {
    settingsAudioDevice.askPermission()
  }
})

onAfterMessageComposed(async () => {
})

onUnmounted(() => {
  teardownAnalyzer()
})

onMounted(() => {
  screenSafeArea.update()
})
</script>

<template>
  <div fixed bottom-0 w-full flex flex-col>
    <BackgroundDialogPicker v-model="backgroundDialogOpen" />
    <KeepAlive>
      <Transition name="fade">
        <ChatHistory
          v-if="!stageViewControlsEnabled"
          variant="mobile"
          :messages="historyMessages"
          :sending="sending"
          :streaming-message="streamingMessage"
          :assistant-label="assistantLabel"
          max-w="[calc(100%-3.5rem)]"
          w-full self-start pb-3 pl-3
          class="chat-history"
          :class="[
            'relative z-20',
          ]"
          @delete-message="handleDeleteMessage($event.index)"
        />
      </Transition>
    </KeepAlive>
    <div relative w-full self-end>
      <div top="50%" translate-y="[-50%]" fixed z-15 px-3>
        <ViewControlInputs ref="viewControlsInputs" :mode="viewControlsActiveMode" />
      </div>
      <div translate-y="[-100%]" absolute right-0 w-full px-3 pb-3 font-sans>
        <div flex="~ col" w-full gap-1>
          <ActionAbout />
          <HearingConfigDialog
            v-model:show="hearingDialogOpen"
            v-model:enabled="enabled"
            v-model:selected-audio-input="selectedAudioInput"
            :audio-inputs="audioInputs"
            :volume-level="volumeLevel"
            :granted="true"
          >
            <button
              border="2 solid neutral-100/60 dark:neutral-800/30"
              bg="neutral-50/70 dark:neutral-800/70"
              w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md
              title="Hearing"
            >
              <Transition name="fade" mode="out-in">
                <IndicatorMicVolume v-if="enabled" size-5 color-class="text-neutral-500 dark:text-neutral-400" />
                <div v-else i-solar:microphone-3-outline size-5 text="neutral-500 dark:neutral-400" />
              </Transition>
            </button>
          </HearingConfigDialog>
          <button border="2 solid neutral-100/60 dark:neutral-800/30" bg="neutral-50/70 dark:neutral-800/70" w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md title="Theme" @click="toggleDark()">
            <Transition name="fade" mode="out-in">
              <div v-if="isDark" i-solar:moon-outline size-5 text="neutral-500 dark:neutral-400" />
              <div v-else i-solar:sun-2-outline size-5 text="neutral-500 dark:neutral-400" />
            </Transition>
          </button>
          <button border="2 solid neutral-100/60 dark:neutral-800/30" bg="neutral-50/70 dark:neutral-800/70" w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md title="Background" @click="backgroundDialogOpen = true">
            <div i-solar:gallery-wide-bold-duotone size-5 text="neutral-500 dark:neutral-400" />
          </button>
          <!-- <button border="2 solid neutral-100/60 dark:neutral-800/30" bg="neutral-50/70 dark:neutral-800/70" w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md title="Language">
            <div i-solar:earth-outline size-5 text="neutral-500 dark:neutral-400" />
          </button> -->
          <RouterLink to="/settings" border="2 solid neutral-100/60 dark:neutral-800/30" bg="neutral-50/70 dark:neutral-800/70" w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md title="Settings">
            <div i-solar:settings-outline size-5 text="neutral-500 dark:neutral-400" />
          </RouterLink>
          <!-- <button border="2 solid neutral-100/60 dark:neutral-800/30" bg="neutral-50/70 dark:neutral-800/70" w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md title="Model">
            <div i-solar:face-scan-circle-outline size-5 text="neutral-500 dark:neutral-400" />
          </button> -->
          <button
            border="2 solid neutral-100/60 dark:neutral-800/30"
            bg="neutral-50/70 dark:neutral-800/70"
            w-fit flex items-center self-end justify-center rounded-xl p-2 backdrop-blur-md
            title="Cleanup Messages"
            @click="cleanupMessages()"
          >
            <div class="i-solar:trash-bin-2-bold-duotone" />
          </button>
          <ActionViewControls v-model="viewControlsActiveMode" @reset="() => viewControlsInputsRef?.resetOnMode()" />
        </div>
      </div>
      <div bg="white dark:neutral-800" max-h-100dvh max-w-100dvw w-full flex gap-1 overflow-auto px-3 pt-2 :style="{ paddingBottom: `${Math.max(Number.parseFloat(screenSafeArea.bottom.value.replace('px', '')), 12)}px` }">
        <button
          w="[calc(1lh+4px+4px)]" h="[calc(1lh+4px+4px)]" aspect-square flex items-center self-end justify-center rounded-full outline-none backdrop-blur-md
          text="neutral-500 hover:neutral-600 dark:neutral-900 dark:hover:neutral-800"
          bg="neutral-100/80 dark:neutral-950/80 hover:neutral-50 dark:hover:neutral-100/80"
          transition="all duration-250 ease-in-out"
          title="上传图片"
          @click="openImagePicker"
        >
          <div i-solar:image-square-bold-duotone />
        </button>
        <BasicTextarea
          v-model="messageInput"
          :placeholder="t('stage.message')"
          border="solid 2 neutral-200/60 dark:neutral-700/60"
          text="neutral-500 hover:neutral-600 dark:neutral-100 dark:hover:neutral-200 placeholder:neutral-400 placeholder:hover:neutral-500 placeholder:dark:neutral-300 placeholder:dark:hover:neutral-400"
          bg="neutral-100/80 dark:neutral-950/80"
          max-h="[10lh]" min-h="[calc(1lh+4px+4px)]"
          w-full resize-none overflow-y-scroll rounded="[1lh]" px-4 py-0.5 outline-none backdrop-blur-md scrollbar-none
          transition="all duration-250 ease-in-out placeholder:all placeholder:duration-250 placeholder:ease-in-out"
          :class="[themeColorsHueDynamic ? 'transition-colors-none placeholder:transition-colors-none' : '']"
          default-height="1lh"
          @submit="handleSubmit"
          @compositionstart="isComposing = true"
          @compositionend="isComposing = false"
        />
        <button
          v-if="messageInput.trim() || isComposing"
          w="[calc(1lh+4px+4px)]" h="[calc(1lh+4px+4px)]" aspect-square flex items-center self-end justify-center rounded-full outline-none backdrop-blur-md
          text="neutral-500 hover:neutral-600 dark:neutral-900 dark:hover:neutral-800"
          bg="primary-50/80 dark:neutral-100/80 hover:neutral-50"
          transition="all duration-250 ease-in-out"
          @click="handleSend"
        >
          <div i-solar:arrow-up-outline />
        </button>
      </div>
      <!-- The uploaded picture, with a way to take it back. -->
      <div
        v-if="uploadedImagePath"
        class="flex items-center gap-2 px-3 pb-1"
      >
        <img
          :src="`${getYXZPrintApiBase()}${uploadedImagePath}`"
          alt="已上传的照片"
          class="h-10 w-10 shrink-0 rounded-lg border border-neutral-200 object-cover dark:border-neutral-700"
        >
        <span class="min-w-0 flex-1 truncate text-xs text-neutral-500 dark:text-neutral-400">
          图片已上传，可以补充你的创作想法
        </span>
        <button
          type="button"
          class="shrink-0 rounded-md px-2 py-1 text-xs text-neutral-400 transition hover:bg-neutral-100 dark:hover:bg-neutral-800"
          @click="removeUploadedImage"
        >
          移除
        </button>
      </div>
      <input
        ref="imageFileInput"
        type="file"
        accept="image/*"
        class="hidden"
        @change="handleImageFileChange"
      >
    </div>
  </div>
</template>

<style scoped>
@keyframes scan {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(400%);
  }
}

.animate-scan {
  animation: scan 2s infinite linear;
}

/*
DO NOT ATTEMPT TO USE backdrop-filter TOGETHER WITH mask-image.

html - Why doesn't blur backdrop-filter work together with mask-image? - Stack Overflow
https://stackoverflow.com/questions/72780266/why-doesnt-blur-backdrop-filter-work-together-with-mask-image
*/
.chat-history {
  --gradient: linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,1) 20%);
  -webkit-mask-image: var(--gradient);
  mask-image: var(--gradient);
  -webkit-mask-size: 100% 100%;
  mask-size: 100% 100%;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-position: bottom;
  mask-position: bottom;
  max-height: 35dvh;
}
</style>
