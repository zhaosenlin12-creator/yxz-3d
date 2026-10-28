import type { SpeechProviderWithExtraOptions } from '@xsai-ext/providers/utils'

import type { VoiceInfo } from '../providers'

import { useLocalStorageManualReset } from '@proj-airi/stage-shared/composables'
import { refManualReset } from '@vueuse/core'
import { generateSpeech } from '@xsai/generate-speech'
import { defineStore, storeToRefs } from 'pinia'
import { computed, onMounted, watch } from 'vue'
import { toXml } from 'xast-util-to-xml'
import { x } from 'xastscript'

import { useProvidersStore } from '../providers'

export function toSignedPercent(value: number): string {
  if (value > 0)
    return `+${value}%`
  if (value < 0)
    return `-${Math.abs(value)}%`
  return '0%'
}

export interface SpeechFallbackCandidate {
  /** Provider id, e.g. `minimax-audio-speech`. */
  providerId: string
  /** Model to use; falls back to the provider's first model. */
  model?: string
  /** Voice id to use; falls back to the provider's first known voice. */
  voice?: string
}

export const useSpeechStore = defineStore('speech', () => {
  const providersStore = useProvidersStore()
  const { allAudioSpeechProvidersMetadata } = storeToRefs(providersStore)

  // State
  const activeSpeechProvider = useLocalStorageManualReset<string>('settings/speech/active-provider', 'speech-noop')
  const activeSpeechModel = useLocalStorageManualReset<string>('settings/speech/active-model', '')
  const activeSpeechVoiceId = useLocalStorageManualReset<string>('settings/speech/voice', '')
  const activeSpeechVoice = refManualReset<VoiceInfo | undefined>(undefined)
  /**
   * Backup speech providers, tried in order when the primary one cannot
   * produce audio.
   *
   * A local voice pack (Voicebox) does not depend on a network round trip,
   * so it is the more stable choice and usually goes first. MiniMax is the
   * cloud backup for when the local service is not running.
   */
  const activeSpeechFallbacks = useLocalStorageManualReset<SpeechFallbackCandidate[]>('settings/speech/fallbacks', [])

  const pitch = useLocalStorageManualReset<number>('settings/speech/pitch', 0)
  const rate = useLocalStorageManualReset<number>('settings/speech/rate', 1)
  const ssmlEnabled = useLocalStorageManualReset<boolean>('settings/speech/ssml-enabled', false)
  const isLoadingSpeechProviderVoices = refManualReset<boolean>(false)
  const speechProviderError = refManualReset<string | null>(null)
  const availableVoices = refManualReset<Record<string, VoiceInfo[]>>(() => ({}))
  const selectedLanguage = useLocalStorageManualReset<string>('settings/speech/language', 'en-US')
  const modelSearchQuery = refManualReset<string>('')

  // A local voice pack that is not running must not spam the console on
  // every reload: remember the unreachable provider for a while and say so
  // only once.
  const VOICE_LIST_FAILURE_COOLDOWN_MS = 60_000
  const voiceListFailureUntil = new Map<string, number>()
  const voiceListWarned = new Set<string>()

  // Computed properties
  const availableSpeechProvidersMetadata = computed(() => allAudioSpeechProvidersMetadata.value)

  // Computed properties
  const supportsModelListing = computed(() => {
    return providersStore.getProviderMetadata(activeSpeechProvider.value)?.capabilities.listModels !== undefined
  })

  const providerModels = computed(() => {
    return providersStore.getModelsForProvider(activeSpeechProvider.value)
  })

  const isLoadingActiveProviderModels = computed(() => {
    return providersStore.isLoadingModels[activeSpeechProvider.value] || false
  })

  const activeProviderModelError = computed(() => {
    return providersStore.modelLoadError[activeSpeechProvider.value] || null
  })

  const filteredModels = computed(() => {
    if (!modelSearchQuery.value.trim()) {
      return providerModels.value
    }

    const query = modelSearchQuery.value.toLowerCase().trim()
    return providerModels.value.filter(model =>
      model.name.toLowerCase().includes(query)
      || model.id.toLowerCase().includes(query)
      || (model.description && model.description.toLowerCase().includes(query)),
    )
  })

  const supportsSSML = computed(() => {
    // Currently only ElevenLabs and some other providers support SSML
    // only part voices are support SSML in cosyvoice-v2 which is provided by alibaba
    if (activeSpeechProvider.value === 'alibaba-cloud-model-studio' && activeSpeechModel.value === 'cosyvoice-v2') {
      return true
    }
    return ['elevenlabs', 'microsoft-speech', 'azure-speech'].includes(activeSpeechProvider.value)
  })

  async function loadVoicesForProvider(provider: string) {
    if (!provider) {
      return []
    }

    const coolingDown = voiceListFailureUntil.get(provider)
    if (coolingDown && Date.now() < coolingDown)
      return availableVoices.value[provider] ?? []

    isLoadingSpeechProviderVoices.value = true
    speechProviderError.value = null

    try {
      const voices = await providersStore.getProviderMetadata(provider).capabilities.listVoices?.(providersStore.getProviderConfig(provider)) || []
      // Reassign to trigger reactivity when adding/updating provider entries
      availableVoices.value = {
        ...availableVoices.value,
        [provider]: voices,
      }
      return voices
    }
    catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      const unreachable = /Failed to fetch|NetworkError|ECONNREFUSED|load failed/i.test(message)

      if (unreachable) {
        voiceListFailureUntil.set(provider, Date.now() + VOICE_LIST_FAILURE_COOLDOWN_MS)
        if (!voiceListWarned.has(provider)) {
          voiceListWarned.add(provider)
          console.warn(`[Speech] 语音服务暂时不可用，已跳过（${provider}）：${message}`)
        }
      }
      else {
        console.error(`Error fetching voices for ${provider}:`, error)
      }
      speechProviderError.value = error instanceof Error ? error.message : 'Unknown error'
      if (provider === 'microsoft-speech') {
        const fallbackVoiceId = activeSpeechVoiceId.value || 'zh-CN-XiaoxiaoNeural'
        availableVoices.value = {
          ...availableVoices.value,
          [provider]: [{
            id: fallbackVoiceId,
            name: fallbackVoiceId,
            provider: 'microsoft-speech',
            languages: [{ code: selectedLanguage.value || 'zh-CN', title: 'Chinese' }],
            gender: 'female',
          }],
        }
        if (!activeSpeechVoice.value) {
          activeSpeechVoice.value = availableVoices.value[provider]?.[0]
        }
      }
      return []
    }
    finally {
      isLoadingSpeechProviderVoices.value = false
    }
  }

  // Get voices for a specific provider
  function getVoicesForProvider(provider: string) {
    return availableVoices.value[provider] || []
  }

  /**
   * The speech providers to try, in order.
   *
   * The first entry is the provider the user picked in the settings; the
   * rest are the configured backups. Every entry carries the model and the
   * voice that belong to *that* provider, because a voice id is only
   * meaningful for the provider it came from.
   */
  function resolveSpeechChain(): SpeechFallbackCandidate[] {
    const chain: SpeechFallbackCandidate[] = []

    if (activeSpeechProvider.value && activeSpeechProvider.value !== 'speech-noop') {
      chain.push({
        providerId: activeSpeechProvider.value,
        model: activeSpeechModel.value,
        voice: activeSpeechVoice.value?.id || activeSpeechVoiceId.value || undefined,
      })
    }

    for (const candidate of activeSpeechFallbacks.value ?? []) {
      if (!candidate?.providerId)
        continue
      if (chain.some(entry => entry.providerId === candidate.providerId))
        continue
      chain.push({
        providerId: candidate.providerId,
        model: candidate.model,
        voice: candidate.voice,
      })
    }

    return chain
  }

  // Watch for provider changes and load voices
  watch(activeSpeechProvider, async (newProvider) => {
    if (newProvider) {
      await loadVoicesForProvider(newProvider)
      // Don't reset voice settings when changing providers to allow for persistence
    }
  }, {
    // REVIEW: should we always load voices on init? What will happen when network is not available?
    immediate: true,
  })

  // The backup providers need their voice list as well: a voice id is only
  // meaningful for the provider it came from, so the chain cannot reuse the
  // primary provider's voice.
  watch(
    () => (activeSpeechFallbacks.value ?? []).map(candidate => candidate?.providerId).filter(Boolean),
    async (providerIds) => {
      for (const providerId of providerIds) {
        if (providerId === activeSpeechProvider.value)
          continue
        if (availableVoices.value[providerId]?.length)
          continue
        await loadVoicesForProvider(providerId)
      }
    },
    { immediate: true, deep: true },
  )

  if (!activeSpeechProvider.value) {
    activeSpeechProvider.value = 'speech-noop'
  }

  watch(
    () => providersStore.configuredSpeechProvidersMetadata.map(provider => provider.id),
    (configuredProviderIds) => {
      if (!activeSpeechProvider.value || activeSpeechProvider.value === 'speech-noop')
        return

      // NOTICE: only reset when the provider has actually been validated and found unconfigured.
      // Skip reset if validation hasn't run yet (validatedCredentialHash is undefined)
      // to avoid a race condition where immediate watcher fires before async validation completes.
      const runtimeState = providersStore.providerRuntimeState[activeSpeechProvider.value]
      if (runtimeState && runtimeState.validatedCredentialHash === undefined)
        return

      // NOTICE: clear stale selection when the currently selected speech provider
      // is no longer configured to avoid implicit fallback behavior from persisted state.
      // NOTE: Do NOT use { immediate: true } here — providers.ts validates credentials
      // asynchronously on startup, so firing immediately would see an empty
      // configuredSpeechProvidersMetadata and incorrectly reset activeSpeechProvider
      // to 'speech-noop', permanently wiping the persisted selection from localStorage.
      if (!configuredProviderIds.includes(activeSpeechProvider.value)) {
        activeSpeechProvider.value = 'speech-noop'
        activeSpeechModel.value = ''
        activeSpeechVoiceId.value = ''
        activeSpeechVoice.value = undefined
      }
    },
  )

  onMounted(() => {
    loadVoicesForProvider(activeSpeechProvider.value).then(() => {
      if (activeSpeechVoiceId.value) {
        activeSpeechVoice.value = availableVoices.value[activeSpeechProvider.value]?.find(voice => voice.id === activeSpeechVoiceId.value)
      }
    })
  })

  watch([activeSpeechVoiceId, availableVoices], ([voiceId, voices]) => {
    if (voiceId) {
      // For OpenAI Compatible, create a custom voice object (no voices available from API)
      if (activeSpeechProvider.value === 'openai-compatible-audio-speech') {
        // Always update to match voiceId (in case it changed)
        activeSpeechVoice.value = {
          id: voiceId,
          name: voiceId,
          description: voiceId,
          previewURL: '',
          languages: [{ code: 'en', title: 'English' }],
          provider: activeSpeechProvider.value,
          gender: 'neutral',
        }
      }
      else {
        // For other providers, find voice in available voices
        const foundVoice = voices[activeSpeechProvider.value]?.find(voice => voice.id === voiceId)
        // Only update if we found a voice, or if activeSpeechVoice is not set
        if (foundVoice || !activeSpeechVoice.value) {
          activeSpeechVoice.value = foundVoice
        }
      }
    }
  }, {
    immediate: true,
    deep: true,
  })

  /**
   * Generate speech using the specified provider and settings
   *
   * @param provider The speech provider instance
   * @param model The model to use
   * @param input The text input to convert to speech
   * @param voice The voice ID to use
   * @param providerConfig Additional provider configuration
   * @returns ArrayBuffer containing the audio data
   */
  async function speech(
    provider: SpeechProviderWithExtraOptions<string, any>,
    model: string,
    input: string,
    voice: string,
    providerConfig: Record<string, any> = {},
  ): Promise<ArrayBuffer> {
    const response = await generateSpeech({
      ...provider.speech(model, {
        ...providerConfig,
      }),
      input,
      voice,
    })

    return response
  }

  function generateSSML(
    text: string,
    voice: VoiceInfo,
    providerConfig?: Record<string, any>,
  ): string {
    const pitch = providerConfig?.pitch
    const speed = providerConfig?.speed
    const volume = providerConfig?.volume

    const prosody = {
      pitch: pitch != null
        ? toSignedPercent(pitch)
        : undefined,
      rate: speed != null
        ? speed !== 1.0
          ? `${speed}`
          : '1'
        : undefined,
      volume: volume != null
        ? toSignedPercent(volume)
        : undefined,
    }

    const hasProsody = Object.values(prosody).some(value => value != null)

    const ssmlXast = x('speak', { 'version': '1.0', 'xmlns': 'http://www.w3.org/2001/10/synthesis', 'xml:lang': voice.languages[0]?.code || 'en-US' }, [
      x('voice', { name: voice.id, gender: voice.gender || 'neutral' }, [
        hasProsody
          ? x('prosody', {
              pitch: prosody.pitch,
              rate: prosody.rate,
              volume: prosody.volume,
            }, [
              text,
            ])
          : text,
      ]),
    ])

    return toXml(ssmlXast)
  }

  const configured = computed(() => {
    if (activeSpeechProvider.value === 'speech-noop')
      return false

    if (!activeSpeechProvider.value)
      return false

    let hasModel = !!activeSpeechModel.value
    let hasVoice = !!activeSpeechVoiceId.value

    // For OpenAI Compatible providers, check provider config as fallback
    if (activeSpeechProvider.value === 'openai-compatible-audio-speech') {
      const providerConfig = providersStore.getProviderConfig(activeSpeechProvider.value)
      hasModel ||= !!providerConfig?.model
      hasVoice ||= !!providerConfig?.voice
    }

    return hasModel && hasVoice
  })

  function resetState() {
    activeSpeechProvider.reset()
    activeSpeechModel.reset()
    activeSpeechVoiceId.reset()
    activeSpeechVoice.reset()
    pitch.reset()
    rate.reset()
    ssmlEnabled.reset()
    selectedLanguage.reset()
    modelSearchQuery.reset()
    availableVoices.reset()
    speechProviderError.reset()
    isLoadingSpeechProviderVoices.reset()
  }

  return {
    // State
    configured,
    activeSpeechProvider,
    activeSpeechModel,
    activeSpeechVoice,
    activeSpeechVoiceId,
    activeSpeechFallbacks,
    pitch,
    rate,
    ssmlEnabled,
    selectedLanguage,
    isLoadingSpeechProviderVoices,
    speechProviderError,
    availableVoices,
    modelSearchQuery,

    // Computed
    availableSpeechProvidersMetadata,
    supportsSSML,
    supportsModelListing,
    providerModels,
    isLoadingActiveProviderModels,
    activeProviderModelError,
    filteredModels,

    // Actions
    speech,
    loadVoicesForProvider,
    getVoicesForProvider,
    resolveSpeechChain,
    generateSSML,
    resetState,
  }
})
