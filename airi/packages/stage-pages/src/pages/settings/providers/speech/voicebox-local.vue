<script setup lang="ts">
import type { SpeechProvider } from '@xsai-ext/providers/utils'

import {
  SpeechPlayground,
  SpeechProviderSettings,
} from '@proj-airi/stage-ui/components'
import { useSpeechStore } from '@proj-airi/stage-ui/stores/modules/speech'
import { useProvidersStore } from '@proj-airi/stage-ui/stores/providers'
import { Callout, FieldInput } from '@proj-airi/ui'
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const providerId = 'voicebox-local'
const defaultModel = 'qwen-custom-voice-1.7B'
const providersStore = useProvidersStore()
const speechStore = useSpeechStore()
const { t } = useI18n()

const providerConfig = computed(() => providersStore.getProviderConfig(providerId) || {})
const model = computed({
  get: () => typeof providerConfig.value.model === 'string' ? providerConfig.value.model : defaultModel,
  set: (value: string) => {
    providersStore.providers[providerId] = {
      ...providersStore.providers[providerId],
      model: value,
      modelSize: value.endsWith('0.6B') ? '0.6B' : '1.7B',
    }
  },
})
const instruct = computed({
  get: () => typeof providerConfig.value.instruct === 'string' ? providerConfig.value.instruct : '温暖、活泼、亲切，带一点可爱的卡通感，语速自然，像宜小智在和用户面对面交流。',
  set: (value: string) => {
    providersStore.providers[providerId] = {
      ...providersStore.providers[providerId],
      instruct: value,
    }
  },
})
const availableVoices = computed(() => speechStore.availableVoices[providerId] || [])
const voiceboxStatus = computed(() => {
  if (speechStore.speechProviderError)
    return `未连接：${speechStore.speechProviderError}`
  if (speechStore.isLoadingSpeechProviderVoices)
    return '正在检测 Voicebox 服务…'
  if (availableVoices.value.length)
    return `已连接，发现 ${availableVoices.value.length} 个声音档案`
  return '尚未发现声音档案，请先在 Voicebox 创建 Eric。'
})

async function handleGenerateSpeech(input: string, voiceId: string) {
  const provider = await providersStore.getProviderInstance(providerId) as SpeechProvider
  if (!provider)
    throw new Error('Voicebox provider 尚未初始化')

  return speechStore.speech(provider, model.value, input, voiceId, {
    ...providerConfig.value,
    instruct: instruct.value,
  })
}

async function refreshVoicebox() {
  await speechStore.loadVoicesForProvider(providerId)
}

onMounted(async () => {
  providersStore.initializeProvider(providerId)
  if (!providersStore.providers[providerId]?.model)
    model.value = defaultModel
  await speechStore.loadVoicesForProvider(providerId)
})

watch(model, async (value) => {
  if (value)
    await speechStore.loadVoicesForProvider(providerId)
})
</script>

<template>
  <SpeechProviderSettings
    :provider-id="providerId"
    :default-model="defaultModel"
  >
    <template #voice-settings>
      <Callout :label="t('settings.pages.providers.provider.voicebox-local.fields.field.voice.label')">
        <p>{{ t('settings.pages.providers.provider.voicebox-local.fields.field.voice.description') }}</p>
        <p class="mt-2 text-sm opacity-80">
          在 Voicebox 中创建 Qwen CustomVoice → Eric（中文男声），再在下方声音档案中选择。Eric 的音色更明亮、有活力，适合宜小智。
        </p>
      </Callout>
      <FieldInput
        v-model="model"
        label="Voicebox model"
        description="推荐使用 Qwen CustomVoice 1.7B；显存较小时可使用 0.6B。"
        placeholder="qwen-custom-voice-1.7B"
      />
      <FieldInput
        v-model="instruct"
        label="宜小智语气"
        description="自然语言控制语速、情绪和卡通感。"
        placeholder="温暖、活泼、亲切，带一点可爱的卡通感"
      />
      <div class="mt-3 flex items-center gap-2 text-sm opacity-80" role="status" aria-live="polite">
        <span>{{ voiceboxStatus }}</span>
        <button type="button" class="rounded bg-primary-500/10 px-2 py-1 text-xs" @click="refreshVoicebox">
          重新检测
        </button>
      </div>
    </template>

    <template #playground>
      <SpeechPlayground
        :available-voices="availableVoices"
        :generate-speech="handleGenerateSpeech"
        :api-key-configured="true"
        :voices-loading="speechStore.isLoadingSpeechProviderVoices || false"
        :default-text="t('settings.pages.providers.provider.voicebox-local.playground.default-text')"
      />
    </template>
  </SpeechProviderSettings>
</template>

<route lang="yaml">
  meta:
    layout: settings
    stageTransition:
      name: slide
</route>
