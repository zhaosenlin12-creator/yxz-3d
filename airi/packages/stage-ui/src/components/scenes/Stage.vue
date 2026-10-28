<script setup lang="ts">
import type { DuckDBWasmDrizzleDatabase } from '@proj-airi/drizzle-duckdb-wasm'
import type { Live2DLipSync, Live2DLipSyncOptions } from '@proj-airi/model-driver-lipsync'
import type { Profile } from '@proj-airi/model-driver-lipsync/shared/wlipsync'
import type { SpeechProviderWithExtraOptions } from '@xsai-ext/providers/utils'
import type { UnElevenLabsOptions } from 'unspeech'

import type { YXZInteractionStatus } from '../../assets/yxz/interaction'
import type { YXZPetFlourish } from '../../composables/use-yxz-pet-motion'
import type { EmotionPayload } from '../../constants/emotions'

import { errorMessageFrom } from '@moeru/std'
import { drizzle } from '@proj-airi/drizzle-duckdb-wasm'
import { getImportUrlBundles } from '@proj-airi/drizzle-duckdb-wasm/bundles/import-url-browser'
import { createLive2DLipSync } from '@proj-airi/model-driver-lipsync'
import { wlipsyncProfile } from '@proj-airi/model-driver-lipsync/shared/wlipsync'
import { createPlaybackManager, createSpeechPipeline, createTtsSegmentStream } from '@proj-airi/pipelines-audio'
import { Live2DScene, useLive2d } from '@proj-airi/stage-ui-live2d'
import { ThreeScene, YXZProceduralScene, YXZRealModelScene } from '@proj-airi/stage-ui-three'
import { animations } from '@proj-airi/stage-ui-three/assets/vrm'
import { createQueue } from '@proj-airi/stream-kit'
import { useBroadcastChannel } from '@vueuse/core'
// import { createTransformers } from '@xsai-transformers/embed'
// import embedWorkerURL from '@xsai-transformers/embed/worker?worker&url'
// import { embed } from '@xsai/embed'
import { generateSpeech } from '@xsai/generate-speech'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import YXZImageScene from './YXZImageScene.vue'
import YXZPetScene from './YXZPetScene.vue'
import YXZPrintPreviewPanel from './YXZPrintPreviewPanel.vue'

import { useDelayMessageQueue, useEmotionsMessageQueue } from '../../composables/queues'
import { useAuthProviderSync } from '../../composables/use-auth-provider-sync'
import { YXZ_PROACTIVE_INTRO_TEXT } from '../../composables/use-yxz-proactive-intro'
import { llmInferenceEndToken } from '../../constants'
import { EMOTION_EmotionMotionName_value, EMOTION_VRMExpressionName_value, EmotionThinkMotionName } from '../../constants/emotions'
import { useAudioContext, useSpeakingStore } from '../../stores/audio'
import { useChatOrchestratorStore } from '../../stores/chat'
import { useAiriCardStore } from '../../stores/modules'
import { useSpeechStore } from '../../stores/modules/speech'
import { useProvidersStore } from '../../stores/providers'
import { useSettings } from '../../stores/settings'
import { useSpeechRuntimeStore } from '../../stores/speech-runtime'
import { shouldRunLive2dLipSyncLoop } from './runtime'

const props = withDefaults(defineProps<{
  paused?: boolean
  focusAt: { x: number, y: number }
  xOffset?: number | string
  yOffset?: number | string
  scale?: number
}>(), { paused: false, scale: 1 })

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })

const db = ref<DuckDBWasmDrizzleDatabase>()
// const transformersProvider = createTransformers({ embedWorkerURL })

const vrmViewerRef = ref<InstanceType<typeof ThreeScene>>()
const live2dSceneRef = ref<InstanceType<typeof Live2DScene>>()

const settingsStore = useSettings()
const {
  stageModelRenderer,
  stageViewControlsEnabled,
  live2dDisableFocus,
  stageModelSelectedUrl,
  stageModelSelected,
  themeColorsHue,
  themeColorsHueDynamic,
  live2dIdleAnimationEnabled,
  live2dAutoBlinkEnabled,
  live2dForceAutoBlinkEnabled,
  live2dExpressionEnabled,
  live2dShadowEnabled,
  live2dMaxFps,
  live2dRenderScale,
} = storeToRefs(settingsStore)
const { mouthOpenSize } = storeToRefs(useSpeakingStore())
const { audioContext, calculateVolume } = useAudioContext()
const currentAudioSource = ref<AudioBufferSourceNode>()

const chatOrchestrator = useChatOrchestratorStore()
const { onBeforeMessageComposed, onBeforeSend, onTokenLiteral, onTokenSpecial, onStreamEnd, onAssistantResponseEnd } = chatOrchestrator
const { sending } = storeToRefs(chatOrchestrator)
const chatHookCleanups: Array<() => void> = []
// WORKAROUND: clear previous handlers on unmount to avoid duplicate calls when this component remounts.
//             We keep per-hook disposers instead of wiping the global chat hooks to play nicely with
//             cross-window broadcast wiring.

const providersStore = useProvidersStore()
useAuthProviderSync()
const live2dStore = useLive2d()
const showStage = ref(true)
const viewUpdateCleanups: Array<() => void> = []

// Caption + Presentation broadcast channels
type CaptionChannelEvent
  = | { type: 'caption-speaker', text: string }
    | { type: 'caption-assistant', text: string }
const { post: postCaption } = useBroadcastChannel<CaptionChannelEvent, CaptionChannelEvent>({ name: 'airi-caption-overlay' })
const assistantCaption = ref('')

type PresentEvent
  = | { type: 'assistant-reset' }
    | { type: 'assistant-append', text: string }
const { post: postPresent } = useBroadcastChannel<PresentEvent, PresentEvent>({ name: 'airi-chat-present' })

viewUpdateCleanups.push(live2dStore.onShouldUpdateView(async () => {
  showStage.value = false
  await settingsStore.updateStageModel()
  setTimeout(() => {
    showStage.value = true
  }, 100)
}))

const audioAnalyser = ref<AnalyserNode>()
const nowSpeaking = ref(false)
const yxzInteractionStatus = ref<YXZInteractionStatus>('idle')
// The one-off action the pet is playing.  The value is cleared once the
// action has been taken, so the same action can be fired again later.
const yxzAction = ref<YXZPetFlourish | ''>('')
let yxzStatusResetTimer: ReturnType<typeof setTimeout> | undefined

function playYXZAction(action: YXZPetFlourish) {
  yxzAction.value = ''
  setTimeout(() => {
    yxzAction.value = action
    setTimeout(() => {
      yxzAction.value = ''
    }, 150)
  }, 30)
}
const lipSyncStarted = ref(false)
const lipSyncLoopId = ref<number>()
const live2dLipSync = ref<Live2DLipSync>()
const live2dLipSyncOptions: Live2DLipSyncOptions = { mouthUpdateIntervalMs: 50, mouthLerpWindowMs: 50 }

const { activeCard } = storeToRefs(useAiriCardStore())
const speechStore = useSpeechStore()
const { ssmlEnabled, activeSpeechProvider, activeSpeechModel, activeSpeechVoice, pitch } = storeToRefs(speechStore)
const activeCardId = computed(() => activeCard.value?.name ?? 'default')
const speechRuntimeStore = useSpeechRuntimeStore()

const { currentMotion } = storeToRefs(useLive2d())

function setYXZInteractionStatus(status: YXZInteractionStatus) {
  if (yxzStatusResetTimer)
    clearTimeout(yxzStatusResetTimer)
  yxzInteractionStatus.value = status
  if (status === 'success') {
    yxzStatusResetTimer = setTimeout(() => {
      yxzInteractionStatus.value = 'idle'
      yxzStatusResetTimer = undefined
    }, 2400)
  }
}

const emotionsQueue = createQueue<EmotionPayload>({
  handlers: [
    async (ctx) => {
      if (stageModelRenderer.value === 'vrm') {
        // console.debug('VRM emotion anime: ', ctx.data)
        const value = EMOTION_VRMExpressionName_value[ctx.data.name]
        if (!value)
          return

        await vrmViewerRef.value!.setExpression(value, ctx.data.intensity)
      }
      else if (stageModelRenderer.value === 'live2d') {
        currentMotion.value = { group: EMOTION_EmotionMotionName_value[ctx.data.name] }
      }
    },
  ],
})

const emotionMessageContentQueue = useEmotionsMessageQueue(emotionsQueue)
emotionMessageContentQueue.onHandlerEvent('emotion', (emotion) => {
  // eslint-disable-next-line no-console
  console.debug('emotion detected', emotion)
})

const delaysQueue = useDelayMessageQueue()
delaysQueue.onHandlerEvent('delay', (delay) => {
  // eslint-disable-next-line no-console
  console.debug('delay detected', delay)
})

// Play special token: delay or emotion
function playSpecialToken(special: string) {
  delaysQueue.enqueue(special)
  emotionMessageContentQueue.enqueue(special)
}
const lipSyncNode = ref<AudioNode>()

async function playFunction(item: Parameters<Parameters<typeof createPlaybackManager<AudioBuffer>>[0]['play']>[0], signal: AbortSignal): Promise<void> {
  if (!audioContext || !item.audio)
    return

  // Ensure audio context is resumed (browsers suspend it by default until user interaction)
  if (audioContext.state === 'suspended') {
    try {
      await audioContext.resume()
    }
    catch {
      return
    }
  }

  const source = audioContext.createBufferSource()
  currentAudioSource.value = source
  source.buffer = item.audio

  source.connect(audioContext.destination)
  if (audioAnalyser.value)
    source.connect(audioAnalyser.value)
  if (lipSyncNode.value)
    source.connect(lipSyncNode.value)

  return new Promise<void>((resolve) => {
    let settled = false
    const resolveOnce = () => {
      if (settled)
        return
      settled = true
      resolve()
    }

    const stopPlayback = () => {
      try {
        source.stop()
        source.disconnect()
      }
      catch {}
      if (currentAudioSource.value === source)
        currentAudioSource.value = undefined
      resolveOnce()
    }

    if (signal.aborted) {
      stopPlayback()
      return
    }

    signal.addEventListener('abort', stopPlayback, { once: true })
    source.onended = () => {
      signal.removeEventListener('abort', stopPlayback)
      stopPlayback()
    }

    try {
      source.start(0)
    }
    catch {
      stopPlayback()
    }
  })
}

const playbackManager = createPlaybackManager<AudioBuffer>({
  play: playFunction,
  maxVoices: 1,
  maxVoicesPerOwner: 1,
  overflowPolicy: 'queue',
  ownerOverflowPolicy: 'steal-oldest',
})

// Tracks whether the configured speech provider actually produced audio for
// the reply that is currently being spoken. When the provider is broken
// (expired key, exhausted quota, unreachable endpoint) 宜小智 used to fall
// completely silent; with these counters the pipeline can report what went
// wrong and try the next provider in the chain.
let providerTtsOkCount = 0
let providerTtsFailCount = 0

// A speech provider that just failed is skipped for a while. The local voice
// pack is the primary one, and on a machine where its service is not running
// every single chunk would otherwise pay a connection attempt before the
// cloud backup takes over.
const PROVIDER_FAILURE_COOLDOWN_MS = 60_000
const providerFailureUntil = new Map<string, number>()

// Cloud speech services bill per request and enforce a requests-per-minute
// limit.  宜小智 speaks the welcome line on every page load and every reply
// is cut into sentence-sized pieces, so a single page visit used to fire
// twenty-odd parallel synthesis calls -- which burned quota and tripped the
// rate limiter ("rate limit exceeded (RPM)").
//
// Two things keep that in check: identical lines are rendered once and then
// reused, and only a couple of requests are in flight at a time.
const TTS_AUDIO_CACHE_LIMIT = 64
const ttsAudioCache = new Map<string, AudioBuffer>()
const TTS_MAX_INFLIGHT = 2
let ttsInFlight = 0
const ttsQueue: Array<() => void> = []

function acquireTtsSlot() {
  if (ttsInFlight < TTS_MAX_INFLIGHT) {
    ttsInFlight++
    return Promise.resolve()
  }
  return new Promise<void>((resolve) => {
    ttsQueue.push(() => {
      ttsInFlight++
      resolve()
    })
  })
}

function releaseTtsSlot() {
  ttsInFlight = Math.max(0, ttsInFlight - 1)
  const next = ttsQueue.shift()
  if (next)
    next()
}

function readCachedTts(key: string) {
  const cached = ttsAudioCache.get(key)
  if (!cached)
    return undefined
  // Refresh the recency so the hot lines stay in the cache.
  ttsAudioCache.delete(key)
  ttsAudioCache.set(key, cached)
  return cached
}

function writeCachedTts(key: string, buffer: AudioBuffer) {
  ttsAudioCache.set(key, buffer)
  while (ttsAudioCache.size > TTS_AUDIO_CACHE_LIMIT) {
    const oldest = ttsAudioCache.keys().next().value
    if (oldest === undefined)
      break
    ttsAudioCache.delete(oldest)
  }
}

function isProviderCoolingDown(providerId: string) {
  const until = providerFailureUntil.get(providerId)
  if (!until)
    return false
  if (Date.now() >= until) {
    providerFailureUntil.delete(providerId)
    return false
  }
  return true
}

// A fragment that carries no pronounceable character (a lone "。" or "？")
// must not be sent to a voice at all: the Edge pack rejects it outright and
// every other voice would read it as a pause anyway. Skipping it here keeps
// the chain from dropping to a worse voice for a fragment nobody can hear.
const SPEAKABLE_TEXT_RE = /[0-9A-Za-zÀ-ɏ぀-ヿ㐀-鿿豈-﫿]/

function hasSpeakableText(text: string) {
  return SPEAKABLE_TEXT_RE.test(text)
}

const speechPipeline = createSpeechPipeline<AudioBuffer>({
  /**
   * Longer chunks than the default.
   *
   * The default splitter cuts a Chinese sentence every dozen words, so one
   * reply became twenty-odd synthesis calls -- twenty-odd requests against
   * the cloud speech quota, and the service answered with "rate limit
   * exceeded (RPM)".  A longer chunk is also closer to how a person
   * speaks, so the voice sounds less chopped up.
   */
  segmenter: (tokens, meta) => createTtsSegmentStream(tokens, meta, {
    minimumWords: 8,
    maximumWords: 30,
  }),
  tts: async (request, signal) => {
    if (signal.aborted)
      return null

    // The primary provider is the one the user picked; the backups take over
    // when it cannot produce audio (cloud key throttled, local voice pack
    // not running, ...). The order is the operator's choice: MiniMax first
    // for the fullest voice pack, the local Voicebox pack behind it, and
    // the free Edge voices close the list. The browser's own speech engine
    // is deliberately not part of the chain.
    const chain = speechStore.resolveSpeechChain()
    if (!chain.length)
      return null

    if (!request.text && !request.special)
      return null

    if (request.text && !hasSpeakableText(request.text))
      return null

    for (const candidate of chain) {
      if (signal.aborted)
        return null

      const providerId = candidate.providerId
      if (isProviderCoolingDown(providerId))
        continue

      const provider = await providersStore.getProviderInstance(providerId) as SpeechProviderWithExtraOptions<string, UnElevenLabsOptions>
      if (!provider) {
        console.error('Failed to initialize speech provider', { provider: providerId })
        continue
      }

      const providerConfig = providersStore.getProviderConfig(providerId)
      const knownVoices = speechStore.getVoicesForProvider(providerId)

      // A voice id only means something for the provider it came from, so
      // every candidate resolves its own voice.
      let model = candidate.model
      let voice = knownVoices.find(item => item.id === candidate.voice) ?? knownVoices[0]

      // The voice list of a provider can still be loading (or the service
      // can be down). The configured voice id is still usable on its own,
      // so do not skip the candidate just because the catalogue is empty.
      if (!voice && candidate.voice) {
        voice = {
          id: candidate.voice,
          name: candidate.voice,
          description: candidate.voice,
          previewURL: '',
          languages: [],
          provider: providerId,
          gender: 'neutral',
        }
      }

      if (providerId === 'openai-compatible-audio-speech') {
        // Always prefer provider config for OpenAI Compatible (user configured it there)
        model = (providerConfig?.model as string) || 'tts-1'
        voice = {
          id: (providerConfig?.voice as string) || 'alloy',
          name: (providerConfig?.voice as string) || 'alloy',
          description: (providerConfig?.voice as string) || 'alloy',
          previewURL: '',
          languages: [{ code: 'en', title: 'English' }],
          provider: providerId,
          gender: 'neutral',
        }
      }

      if (!model || !voice)
        continue

      const input = ssmlEnabled.value
        ? speechStore.generateSSML(request.text, voice, { ...providerConfig, pitch: pitch.value })
        : request.text

      // The same line is spoken over and over (the welcome greeting on every
      // page load, a repeated answer).  Rendering it once and replaying the
      // buffer keeps the cloud speech quota for the parts that are new.
      const cacheKey = `${providerId}|${model}|${voice.id}|${input}`
      const cached = readCachedTts(cacheKey)
      if (cached) {
        providerTtsOkCount += 1
        return cached
      }

      try {
        console.info('[Stage] Generating speech', {
          provider: providerId,
          model,
          voice: voice.id,
          textLength: request.text.length,
        })
        await acquireTtsSlot()
        let res: ArrayBuffer
        try {
          res = await generateSpeech({
            ...provider.speech(model, providerConfig),
            input,
            voice: voice.id,
          })
        }
        finally {
          releaseTtsSlot()
        }

        if (signal.aborted)
          return null

        if (!res || res.byteLength === 0)
          continue

        const audioBuffer = await audioContext.decodeAudioData(res)
        writeCachedTts(cacheKey, audioBuffer)
        providerTtsOkCount += 1
        return audioBuffer
      }
      catch (error) {
        providerTtsFailCount += 1
        providerFailureUntil.set(providerId, Date.now() + PROVIDER_FAILURE_COOLDOWN_MS)
        // Put the reason into the message itself: the extra object is not
        // visible when the console only prints the first argument, which used
        // to hide the actual MiniMax error code from the operator.
        console.error(`[Stage] Provider TTS failed: ${errorMessageFrom(error) ?? 'Unknown error'}`, {
          provider: providerId,
          model,
          voice: voice.id,
        })
        // Try the next provider in the chain.
      }
    }

    return null
  },
  playback: playbackManager,
})

void speechRuntimeStore.registerHost(speechPipeline)

speechPipeline.on('onSpecial', (segment) => {
  if (segment.special)
    playSpecialToken(segment.special)
})

playbackManager.onEnd(({ item }) => {
  if (item.special)
    playSpecialToken(item.special)

  nowSpeaking.value = false
  mouthOpenSize.value = 0
  setYXZInteractionStatus('success')
})

playbackManager.onStart(({ item }) => {
  nowSpeaking.value = true
  setYXZInteractionStatus('speaking')
  // NOTICE: postCaption and postPresent may throw errors if the BroadcastChannel is closed
  // (e.g., when navigating away from the page). We wrap these in try-catch to prevent
  // breaking playback when the channel is unavailable.
  assistantCaption.value += ` ${item.text}`
  try {
    postCaption({ type: 'caption-assistant', text: assistantCaption.value })
  }
  catch {
    // BroadcastChannel may be closed - don't break playback
  }
  try {
    postPresent({ type: 'assistant-append', text: item.text })
  }
  catch {
    // BroadcastChannel may be closed - don't break playback
  }
})

function startLipSyncLoop() {
  if (lipSyncLoopId.value)
    return

  const tick = () => {
    if (!nowSpeaking.value) {
      mouthOpenSize.value = 0
    }
    else if (stageModelRenderer.value === 'live2d' && live2dLipSync.value) {
      mouthOpenSize.value = live2dLipSync.value.getMouthOpen()
    }
    else if (stageModelRenderer.value === 'image' && stageModelSelected.value === 'preset-yxz' && audioAnalyser.value) {
      // YXZ has dedicated closed/open mouth geometry rather than Live2D
      // parameters. Feed it a smoothed, bounded level from the same TTS
      // analyser used by playback, so the mouth follows real speech energy.
      const level = calculateVolume(audioAnalyser.value)
      mouthOpenSize.value = Math.min(1, Math.max(0, level))
    }
    else {
      mouthOpenSize.value = 0
    }
    lipSyncLoopId.value = requestAnimationFrame(tick)
  }

  lipSyncLoopId.value = requestAnimationFrame(tick)
}

function stopLipSyncLoop() {
  if (lipSyncLoopId.value) {
    cancelAnimationFrame(lipSyncLoopId.value)
    lipSyncLoopId.value = undefined
  }

  mouthOpenSize.value = 0
}

function resetLive2dLipSync() {
  stopLipSyncLoop()

  try {
    lipSyncNode.value?.disconnect()
  }
  catch {

  }

  lipSyncNode.value = undefined
  live2dLipSync.value = undefined
  lipSyncStarted.value = false
}

function syncLipSyncLoop() {
  const shouldRunLive2d = shouldRunLive2dLipSyncLoop({
    stageModelRenderer: stageModelRenderer.value,
    paused: Boolean(props.paused),
  }) && lipSyncStarted.value
  const shouldRunYXZ = stageModelRenderer.value === 'image'
    && stageModelSelected.value === 'preset-yxz'
    && !props.paused
  if (shouldRunLive2d || shouldRunYXZ) {
    startLipSyncLoop()
    return
  }

  stopLipSyncLoop()
}

async function setupLipSync() {
  if (stageModelRenderer.value !== 'live2d') {
    resetLive2dLipSync()
    return
  }

  if (lipSyncStarted.value)
    return

  try {
    const lipSync = await createLive2DLipSync(audioContext, wlipsyncProfile as Profile, live2dLipSyncOptions)
    live2dLipSync.value = lipSync
    lipSyncNode.value = lipSync.node
    await audioContext.resume()
    lipSyncStarted.value = true
    syncLipSyncLoop()
  }
  catch (error) {
    resetLive2dLipSync()
    console.error('Failed to setup Live2D lip sync', error)
  }
}

function setupAnalyser() {
  if (!audioAnalyser.value) {
    audioAnalyser.value = audioContext.createAnalyser()
  }
}

let currentChatIntent: ReturnType<typeof speechRuntimeStore.openIntent> | null = null
const assistantResponseText = ref('')
const welcomeSpeechBusy = ref(false)
const welcomeSpeechNeedsGesture = ref(false)
const yxzRealModelFailed = ref(false)
// The sprite pet is the character the stage shows; the model is the
// fallback for a stage that cannot draw it.
const yxzPetFailed = ref(false)

function handleYXZChatRecovery() {
  currentChatIntent?.cancel('chat-send-recovery')
  currentChatIntent = null
  playbackManager.stopAll('chat-send-recovery')
  setYXZInteractionStatus('idle')
}

async function speakYXZWelcome() {
  if (stageModelSelected.value !== 'preset-yxz' || welcomeSpeechBusy.value)
    return

  welcomeSpeechBusy.value = true
  setYXZInteractionStatus('speaking')
  // The character waves while it says hello.
  playYXZAction('wave')
  playbackManager.stopAll('new-welcome')

  try {
    // The speech chain (MiniMax -> local Voicebox -> free Edge voices)
    // resolves itself, so the greeting goes through the same pipeline as
    // every other line.
    welcomeSpeechNeedsGesture.value = false
    const intent = speechRuntimeStore.openIntent({
      ownerId: activeCardId.value,
      priority: 'normal',
      behavior: 'queue',
    })
    intent.writeLiteral(YXZ_PROACTIVE_INTRO_TEXT)
    intent.writeFlush()
    intent.end()
  }
  finally {
    welcomeSpeechBusy.value = false
  }
}

chatHookCleanups.push(onBeforeMessageComposed(async () => {
  setYXZInteractionStatus('listening')
  playbackManager.stopAll('new-message')
  providerTtsOkCount = 0
  providerTtsFailCount = 0

  setupAnalyser()
  await setupLipSync()
  // Reset assistant caption for a new message
  assistantCaption.value = ''
  assistantResponseText.value = ''
  try {
    postCaption({ type: 'caption-assistant', text: '' })
  }
  catch (error) {
    // BroadcastChannel may be closed if user navigated away - don't break flow
    console.warn('[Stage] Failed to post caption reset (channel may be closed)', { error })
  }
  try {
    postPresent({ type: 'assistant-reset' })
  }
  catch (error) {
    // BroadcastChannel may be closed if user navigated away - don't break flow
    console.warn('[Stage] Failed to post present reset (channel may be closed)', { error })
  }

  if (currentChatIntent) {
    currentChatIntent.cancel('new-message')
    currentChatIntent = null
  }

  currentChatIntent = speechRuntimeStore.openIntent({
    ownerId: activeCardId.value,
    priority: 'normal',
    behavior: 'queue',
  })
}))

chatHookCleanups.push(onBeforeSend(async () => {
  setYXZInteractionStatus('thinking')
  currentMotion.value = { group: EmotionThinkMotionName }
}))

chatHookCleanups.push(onTokenLiteral(async (literal) => {
  if (!nowSpeaking.value)
    setYXZInteractionStatus('thinking')
  assistantResponseText.value += literal
  currentChatIntent?.writeLiteral(literal)
}))

chatHookCleanups.push(onTokenSpecial(async (special) => {
  // console.debug('Stage received special token:', special)
  currentChatIntent?.writeSpecial(special)
}))

chatHookCleanups.push(onStreamEnd(async () => {
  delaysQueue.enqueue(llmInferenceEndToken)
  currentChatIntent?.writeFlush()
}))

chatHookCleanups.push(onAssistantResponseEnd(async (_message) => {
  currentChatIntent?.end()
  currentChatIntent = null

  if (nowSpeaking.value)
    return

  // NOTICE: speechPipeline already streams TTS for the configured provider
  // (e.g. minimax-audio-speech) via onTokenLiteral + writeLiteral. Re-speaking
  // the whole reply here caused double playback (provider voice + second
  // voice at the same time).
  //
  // The speech chain is MiniMax -> local Voicebox -> free Edge voices, so a
  // broken key or an offline voice pack is already covered. The browser's
  // own speech engine is not used as a hidden extra fallback: it sounds flat
  // and it depends on what the operating system happens to expose.
  if (activeSpeechProvider.value !== 'speech-noop' && activeSpeechProvider.value) {
    if (providerTtsOkCount === 0 && providerTtsFailCount > 0 && assistantResponseText.value.trim()) {
      console.warn('[Stage] Provider TTS produced no audio', {
        provider: activeSpeechProvider.value,
        model: activeSpeechModel.value,
        failures: providerTtsFailCount,
      })
    }
    return
  }

  setYXZInteractionStatus('idle')
  console.warn('[Stage] No audible TTS was produced', {
    provider: activeSpeechProvider.value,
    model: activeSpeechModel.value,
    voice: activeSpeechVoice.value?.id,
    textLength: assistantResponseText.value.length,
  })
  // const res = await embed({
  //   ...transformersProvider.embed('Xenova/nomic-embed-text-v1'),
  //   input: message,
  // })

  // await db.value?.execute(`INSERT INTO memory_test (vec) VALUES (${JSON.stringify(res.embedding)});`)
}))

// Resume audio context on first user interaction (browser requirement)
let audioContextResumed = false
function resumeAudioContextOnInteraction() {
  if (audioContextResumed || !audioContext)
    return
  audioContextResumed = true
  audioContext.resume().catch(() => {
    // Ignore errors - audio context will be resumed when needed
  })
}

// Add event listeners for user interaction
if (typeof window !== 'undefined') {
  const events = ['click', 'touchstart', 'keydown']
  events.forEach((event) => {
    window.addEventListener(event, resumeAudioContextOnInteraction, { once: true, passive: true })
  })
}

onMounted(async () => {
  window.addEventListener('yxz:chat-recovery', handleYXZChatRecovery)
  db.value = drizzle({ connection: { bundles: getImportUrlBundles() } })
  await db.value.execute(`CREATE TABLE memory_test (vec FLOAT[768]);`)
  if (stageModelSelected.value === 'preset-yxz')
    setTimeout(() => void speakYXZWelcome(), 180)
})

watch([stageModelRenderer, () => props.paused], ([renderer]) => {
  if (renderer !== 'live2d') {
    resetLive2dLipSync()
    return
  }

  syncLipSyncLoop()
}, { immediate: true })

// A provider can fail before the first token arrives. In that path the normal
// response hooks never run, so use the orchestrator's settled flag as a second
// recovery signal and return the avatar to an idle, retryable state.
watch(sending, (isSending, wasSending) => {
  if (wasSending && !isSending && yxzInteractionStatus.value === 'thinking')
    setYXZInteractionStatus('idle')
})

function canvasElement() {
  if (stageModelRenderer.value === 'live2d')
    return live2dSceneRef.value?.canvasElement()

  else if (stageModelRenderer.value === 'vrm')
    return vrmViewerRef.value?.canvasElement()
}

function readRenderTargetRegionAtClientPoint(clientX: number, clientY: number, radius: number) {
  if (stageModelRenderer.value !== 'vrm')
    return null

  return vrmViewerRef.value?.readRenderTargetRegionAtClientPoint?.(clientX, clientY, radius) ?? null
}

onUnmounted(() => {
  if (yxzStatusResetTimer)
    clearTimeout(yxzStatusResetTimer)
  resetLive2dLipSync()
  window.removeEventListener('yxz:chat-recovery', handleYXZChatRecovery)
  chatHookCleanups.forEach(dispose => dispose?.())
  viewUpdateCleanups.forEach(dispose => dispose?.())
})

watch(stageModelSelected, () => {
  yxzRealModelFailed.value = false
  yxzPetFailed.value = false
})

defineExpose({
  canvasElement,
  readRenderTargetRegionAtClientPoint,
})
</script>

<template>
  <div relative h-full w-full>
    <div h-full w-full>
      <Live2DScene
        v-if="stageModelRenderer === 'live2d' && showStage"
        ref="live2dSceneRef"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :model-src="stageModelSelectedUrl"
        :model-id="stageModelSelected"
        :focus-at="focusAt"
        :mouth-open-size="mouthOpenSize"
        :paused="paused"
        :x-offset="xOffset"
        :y-offset="yOffset"
        :scale="scale"
        :disable-focus-at="live2dDisableFocus"
        :theme-colors-hue="themeColorsHue"
        :theme-colors-hue-dynamic="themeColorsHueDynamic"
        :live2d-idle-animation-enabled="live2dIdleAnimationEnabled"
        :live2d-auto-blink-enabled="live2dAutoBlinkEnabled"
        :live2d-force-auto-blink-enabled="live2dForceAutoBlinkEnabled"
        :live2d-expression-enabled="live2dExpressionEnabled"
        :live2d-shadow-enabled="live2dShadowEnabled"
        :live2d-max-fps="live2dMaxFps"
        :live2d-render-scale="live2dRenderScale"
      />
      <YXZImageScene
        v-if="stageModelRenderer === 'image' && stageModelSelected !== 'preset-yxz' && showStage"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :model-src="stageModelSelectedUrl"
        :status="yxzInteractionStatus"
        :paused="paused"
        :x-offset="xOffset"
        :y-offset="yOffset"
        :scale="scale"
      />
      <YXZPetScene
        v-if="stageModelRenderer === 'image' && stageModelSelected === 'preset-yxz' && showStage && !yxzPetFailed"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :status="yxzInteractionStatus"
        :action="yxzAction"
        :speaking-level="mouthOpenSize"
        :message="assistantResponseText"
        :paused="paused"
        :focus-at="focusAt"
        :x-offset="xOffset"
        :y-offset="yOffset"
        :scale="scale"
        @error="yxzPetFailed = true"
      />
      <YXZRealModelScene
        v-if="stageModelRenderer === 'image' && stageModelSelected === 'preset-yxz' && showStage && yxzPetFailed && !yxzRealModelFailed"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :status="yxzInteractionStatus"
        :speaking-level="mouthOpenSize"
        :paused="paused"
        :x-offset="xOffset"
        :y-offset="yOffset"
        :scale="scale"
        @error="yxzRealModelFailed = true"
      />
      <YXZProceduralScene
        v-if="stageModelRenderer === 'image' && stageModelSelected === 'preset-yxz' && showStage && yxzRealModelFailed"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100"
        h-full w-full flex-1
        :status="yxzInteractionStatus"
        :paused="paused"
      />
      <button
        v-if="stageModelRenderer === 'image' && stageModelSelected === 'preset-yxz'"
        type="button"
        class="yxz-welcome-replay"
        :disabled="welcomeSpeechBusy"
        aria-label="播放宜小智欢迎语"
        @click="void speakYXZWelcome()"
      >
        {{ welcomeSpeechBusy ? '正在播报…' : welcomeSpeechNeedsGesture ? '🔊 点一下让我开口' : '🔊 再听一次欢迎语' }}
      </button>
      <ThreeScene
        v-if="stageModelRenderer === 'vrm' && showStage"
        ref="vrmViewerRef"
        v-model:state="componentState"
        min-w="50% <lg:full" min-h="100 sm:100" h-full w-full flex-1
        :model-src="stageModelSelectedUrl"
        :idle-animation="animations.idleLoop.toString()"
        :paused="paused"
        :show-axes="stageViewControlsEnabled"
        :current-audio-source="currentAudioSource"
        @error="console.error"
      />
      <YXZPrintPreviewPanel
        v-if="stageModelRenderer === 'image' && showStage"
        @status="setYXZInteractionStatus"
      />
    </div>
  </div>
</template>

<style scoped>
.yxz-welcome-replay {
  position: absolute;
  /* The chat column floats over the right hand side of the stage, and a
     button behind a panel is a button nobody can see or click.  The
     greeting is the one thing the visitor has to be able to hear
     again, so it goes to the empty stage on the left. */
  left: 1rem;
  right: auto;
  bottom: 1rem;
  z-index: 4;
  padding: .45rem .7rem;
  border: 1px solid rgba(24, 168, 224, .3);
  border-radius: .7rem;
  background: rgba(255, 255, 255, .88);
  color: #15547c;
  box-shadow: 0 5px 16px rgba(27, 111, 177, .12);
  cursor: pointer;
  font-size: .75rem;
}

.yxz-welcome-replay:disabled {
  cursor: wait;
  opacity: .7;
}
</style>
