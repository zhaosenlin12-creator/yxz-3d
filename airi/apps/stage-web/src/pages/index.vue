<script setup lang="ts">
import type { ChatProvider } from '@xsai-ext/providers/utils'

import Header from '@proj-airi/stage-layouts/components/Layouts/Header.vue'
import InteractiveArea from '@proj-airi/stage-layouts/components/Layouts/InteractiveArea.vue'
import MobileHeader from '@proj-airi/stage-layouts/components/Layouts/MobileHeader.vue'
import MobileInteractiveArea from '@proj-airi/stage-layouts/components/Layouts/MobileInteractiveArea.vue'
import workletUrl from '@proj-airi/stage-ui/workers/vad/process.worklet?worker&url'

import { BackgroundProvider } from '@proj-airi/stage-layouts/components/Backgrounds'
import { useBackgroundThemeColor } from '@proj-airi/stage-layouts/composables/theme-color'
import { useBackgroundStore } from '@proj-airi/stage-layouts/stores/background'
import { HoloCoupon } from '@proj-airi/stage-ui/components'
import { WidgetStage } from '@proj-airi/stage-ui/components/scenes'
import { useAudioRecorder } from '@proj-airi/stage-ui/composables/audio/audio-recorder'
import { useVAD } from '@proj-airi/stage-ui/stores/ai/models/vad'
import { useChatOrchestratorStore } from '@proj-airi/stage-ui/stores/chat'
import { useLive2d } from '@proj-airi/stage-ui/stores/live2d'
import { useConsciousnessStore } from '@proj-airi/stage-ui/stores/modules/consciousness'
import { useHearingSpeechInputPipeline } from '@proj-airi/stage-ui/stores/modules/hearing'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { useSettingsAudioDevice } from '@proj-airi/stage-ui/stores/settings'
import { breakpointsTailwind, useBreakpoints, useMouse } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'

const paused = ref(false)

function handleSettingsOpen(open: boolean) {
  paused.value = open
}

const positionCursor = useMouse()
const { scale, position, positionInPercentageString } = storeToRefs(useLive2d())
const breakpoints = useBreakpoints(breakpointsTailwind)
const isMobile = breakpoints.smaller('md')

const backgroundStore = useBackgroundStore()
const { selectedOption, sampledColor } = storeToRefs(backgroundStore)
const backgroundSurface = useTemplateRef<InstanceType<typeof BackgroundProvider>>('backgroundSurface')

const { syncBackgroundTheme } = useBackgroundThemeColor({ backgroundSurface, selectedOption, sampledColor })
onMounted(() => syncBackgroundTheme())

// Audio + transcription pipeline (mirrors stage-tamagotchi)
const settingsAudioDeviceStore = useSettingsAudioDevice()
const { stream, enabled } = storeToRefs(settingsAudioDeviceStore)
const { startRecord, stopRecord, onStopRecord } = useAudioRecorder(stream)
const hearingPipeline = useHearingSpeechInputPipeline()
const { transcribeForRecording } = hearingPipeline
const { supportsStreamInput } = storeToRefs(hearingPipeline)
const providersStore = useProvidersStore()
const consciousnessStore = useConsciousnessStore()
const { activeProvider: activeChatProvider, activeModel: activeChatModel } = storeToRefs(consciousnessStore)
const chatStore = useChatOrchestratorStore()

const shouldUseStreamInput = computed(() => supportsStreamInput.value && !!stream.value)

const {
  init: initVAD,
  dispose: disposeVAD,
  start: startVAD,
  loaded: vadLoaded,
} = useVAD(workletUrl, {
  threshold: ref(0.6),
  onSpeechStart: () => handleSpeechStart(),
  onSpeechEnd: () => handleSpeechEnd(),
})

let stopOnStopRecord: (() => void) | undefined

async function startAudioInteraction() {
  try {
    await initVAD()
    if (stream.value)
      await startVAD(stream.value)

    // Hook once
    stopOnStopRecord = onStopRecord(async (recording) => {
      const text = await transcribeForRecording(recording)
      if (!text || !text.trim())
        return

      try {
        const provider = await providersStore.getProviderInstance(activeChatProvider.value)
        if (!provider || !activeChatModel.value)
          return

        await chatStore.ingest(text, { model: activeChatModel.value, chatProvider: provider as ChatProvider })
      }
      catch (err) {
        console.error('Failed to send chat from voice:', err)
      }
    })
  }
  catch (e) {
    console.error('Audio interaction init failed:', e)
  }
}

async function handleSpeechStart() {
  // For streaming providers, ChatArea component handles transcription manually
  // The main page should not start automatic transcription to avoid duplicate sessions
  if (shouldUseStreamInput.value) {
    return
  }

  startRecord()
}

async function handleSpeechEnd() {
  if (shouldUseStreamInput.value) {
    // Keep streaming session alive; idle timer in pipeline will handle teardown.
    return
  }

  stopRecord()
}

function stopAudioInteraction() {
  try {
    stopOnStopRecord?.()
    stopOnStopRecord = undefined
    disposeVAD()
  }
  catch {}
}

watch(enabled, async (val) => {
  if (val) {
    await startAudioInteraction()
  }
  else {
    stopAudioInteraction()
  }
}, { immediate: true })

onUnmounted(() => {
  stopAudioInteraction()
})

watch([stream, () => vadLoaded.value], async ([s, loaded]) => {
  if (enabled.value && loaded && s) {
    try {
      await startVAD(s)
    }
    catch (e) {
      console.error('Failed to start VAD with stream:', e)
    }
  }
})
</script>

<template>
  <BackgroundProvider
    ref="backgroundSurface"
    class="widgets top-widgets"
    :background="selectedOption"
    :top-color="sampledColor"
  >
    <!--
      NOTE: the stage column must not be locked to the viewport height.
      宜小智的 2D 精灵画布按 2:1 宽高比铺满整行，窄屏 / 笔记本上会比视口更高，
      之前用 `h-100dvh of-hidden` 会把角色的脚直接裁掉，而且页面完全无法滚动。
      改成 `min-h-100dvh` + 允许纵向滚动后，超出部分可以往下滚到，
      背景层也会跟着容器一起长高，不会出现空白。
    -->
    <div relative flex="~ col" z-2 min-h-100dvh w-100vw of-x-hidden>
      <!-- header -->
      <div class="px-0 py-1 md:px-3 md:py-3" w-full gap-2>
        <Header class="hidden md:flex" />
        <MobileHeader class="flex md:hidden" />
      </div>
      <!-- 活动标题层（DOM 渲染，任何分辨率都不贴边、不越界） -->
      <div class="stage-title-layer">
        <div class="stage-title-brand">
          <span class="stage-brand-mark">YCSL</span>
          <span class="stage-brand-slogan">数理创未来·智慧启新程</span>
        </div>
        <div class="stage-title-block">
          <h1 class="stage-title-line-1">宜昌市第四届中小学生数理文化活动</h1>
          <h2 class="stage-title-line-2">暨人工智能教育成果交流研讨会</h2>
        </div>
        <div class="stage-title-year">2026</div>
      </div>
      <!-- page -->
      <div relative flex="~ 1 row gap-y-0 gap-x-2 <md:col">
        <WidgetStage
          style="--yxz-bubble-top: 12%; margin-left: 2vw"
          flex-1 min-w="1/2"
          :paused="paused"
          :focus-at="{
            x: positionCursor.x.value,
            y: positionCursor.y.value,
          }"
          :x-offset="`${isMobile ? position.x : position.x - 16}%`"
          :y-offset="positionInPercentageString.y"
          :scale="scale"
        />
        <InteractiveArea v-if="!isMobile" h="85dvh" absolute right-3 flex flex-1 flex-col max-w="640px" min-w="32%" />
        <MobileInteractiveArea v-if="isMobile" @settings-open="handleSettingsOpen" />
      </div>
      <HoloCoupon />
    </div>
  </BackgroundProvider>
</template>

<style scoped>
/* 活动标题层：DOM 文字叠加在无字背景之上，居中排布、安全边距充足 */
.stage-title-layer {
  position: absolute;
  inset: 0;
  z-index: 5;
  pointer-events: none;
}

.stage-title-block {
  position: absolute;
  top: 4.5vh;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6vh;
  text-align: center;
  white-space: nowrap;
}

.stage-title-line-1 {
  margin: 0;
  color: #f4f9ff;
  font-size: clamp(20px, 2.7vw, 46px);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-shadow: 0 2px 14px rgba(6, 24, 52, 0.55), 0 0 30px rgba(80, 170, 255, 0.25);
}

.stage-title-line-2 {
  margin: 0;
  color: #cfe6ff;
  font-size: clamp(14px, 1.6vw, 28px);
  font-weight: 500;
  letter-spacing: 0.14em;
  text-shadow: 0 1px 10px rgba(6, 24, 52, 0.5);
}

.stage-title-brand {
  position: absolute;
  top: 5vh;
  left: 2.5vw;
  display: flex;
  align-items: center;
  gap: 0.8vw;
}

.stage-brand-mark {
  color: #ffffff;
  font-size: clamp(13px, 1.15vw, 22px);
  font-weight: 800;
  letter-spacing: 0.12em;
  text-shadow: 0 1px 8px rgba(6, 24, 52, 0.6);
}

.stage-brand-slogan {
  color: #bfe0ff;
  font-size: clamp(11px, 0.95vw, 17px);
  letter-spacing: 0.1em;
  text-shadow: 0 1px 6px rgba(6, 24, 52, 0.55);
}

.stage-title-year {
  position: absolute;
  top: 4.5vh;
  right: 2.5vw;
  color: #e2f0ff;
  font-size: clamp(18px, 2.2vw, 38px);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-shadow: 0 2px 10px rgba(6, 24, 52, 0.5);
}

@media (max-width: 900px) {
  .stage-title-block { top: 3.5vh; }
  .stage-title-line-1 { font-size: clamp(16px, 4.4vw, 26px); }
  .stage-title-line-2 { font-size: clamp(12px, 3vw, 17px); }
  .stage-brand-slogan { display: none; }
  .stage-title-year { top: 3.5vh; }
}
</style>

<route lang="yaml">
name: IndexScenePage
meta:
  layout: stage
  stageTransition:
    name: bubble-wave-out
</route>
