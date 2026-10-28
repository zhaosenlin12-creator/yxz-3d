import type { ChatProvider, ModelProvider } from '@xsai-ext/providers/utils'

import type { ModelInfo } from '../../types'

import { createMinimax, createMinimaxCn } from '@xsai-ext/providers/create'
import { z } from 'zod'

import { createMinimaxKeyRotatingFetch, splitApiKeys } from '../../../../utils/minimax-key-rotation'
import { ProviderValidationCheck } from '../../types'
import { createOpenAICompatibleValidators } from '../../validators'
import { defineProvider } from '../registry'

/**
 * Wrap a MiniMax provider so a request is retried with the next configured
 * key when the current one is rejected.
 *
 * MiniMax answers an exhausted Token Plan with HTTP 200 plus an error body
 * instead of a 4xx, so the rotation has to happen inside the fetch: the first
 * chunk of the answer is inspected before it reaches the caller.
 */
function withMinimaxKeyRotation(
  provider: ChatProvider & ModelProvider,
  rawApiKey: unknown,
): ChatProvider & ModelProvider {
  const keys = splitApiKeys(rawApiKey)
  if (keys.length <= 1)
    return provider

  const rotatingFetch = createMinimaxKeyRotatingFetch(keys)

  return {
    ...provider,
    chat: model => ({ ...provider.chat(model), fetch: rotatingFetch }),
  }
}

const minimaxCnConfigSchema = z.object({
  apiKey: z
    .string('API Key'),
  baseUrl: z
    .string('Base URL')
    .optional()
    .default('https://api.minimaxi.com/v1/'),
})

type MinimaxCnConfig = z.input<typeof minimaxCnConfigSchema>

const minimaxGlobalConfigSchema = z.object({
  apiKey: z
    .string('API Key'),
  baseUrl: z
    .string('Base URL')
    .optional()
    .default('https://api.minimax.io/v1/'),
})

type MinimaxGlobalConfig = z.input<typeof minimaxGlobalConfigSchema>

const minimaxModels: ModelInfo[] = [
  {
    id: 'MiniMax-M2.7',
    name: 'MiniMax M2.7',
    provider: 'minimax',
    description: 'Latest flagship model with enhanced reasoning and coding',
  },
  {
    id: 'MiniMax-M2.7-highspeed',
    name: 'MiniMax M2.7 Highspeed',
    provider: 'minimax',
    description: 'High-speed version of M2.7 for low-latency scenarios',
  },
  {
    id: 'MiniMax-M2.5',
    name: 'MiniMax M2.5',
    provider: 'minimax',
    description: 'Top performance and cost-effectiveness for complex tasks',
  },
  {
    id: 'MiniMax-M2.5-highspeed',
    name: 'MiniMax M2.5 Highspeed',
    provider: 'minimax',
    description: 'M2.5 high-speed version with same quality',
  },
  {
    id: 'MiniMax-M2.1',
    name: 'MiniMax M2.1',
    provider: 'minimax',
    description: 'Strong multilingual programming capabilities',
  },
  {
    id: 'MiniMax-M2.1-highspeed',
    name: 'MiniMax M2.1 Highspeed',
    provider: 'minimax',
    description: 'M2.1 high-speed version with same quality',
  },
  {
    id: 'M2-her',
    name: 'MiniMax M2-her',
    provider: 'minimax',
    description: 'Specialized for roleplay and multi-turn dialogue',
  },
  {
    id: 'MiniMax-M2',
    name: 'MiniMax M2',
    provider: 'minimax',
    description: 'Designed for efficient coding and agent workflows',
  },
]

export const providerMinimax = defineProvider<MinimaxCnConfig>({
  id: 'minimax',
  name: 'MiniMax',
  nameLocalize: ({ t }) => t('settings.pages.providers.provider.minimax.title'),
  description: 'minimaxi.com',
  descriptionLocalize: ({ t }) => t('settings.pages.providers.provider.minimax.description'),
  tasks: ['chat'],
  icon: 'i-lobe-icons:minimax',
  iconColor: 'i-lobe-icons:minimax-color',

  createProviderConfig: ({ t }) => minimaxCnConfigSchema.extend({
    apiKey: minimaxCnConfigSchema.shape.apiKey.meta({
      labelLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.label'),
      descriptionLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.description'),
      placeholderLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.placeholder'),
      type: 'password',
    }),
    baseUrl: minimaxCnConfigSchema.shape.baseUrl.meta({
      labelLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.label'),
      descriptionLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.description'),
      placeholderLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.placeholder'),
    }),
  }),
  createProvider(config) {
    return withMinimaxKeyRotation(createMinimaxCn(config.apiKey, config.baseUrl), config.apiKey)
  },

  extraMethods: {
    listModels: async () => minimaxModels,
  },
  validationRequiredWhen(config) {
    return !!config.apiKey?.trim()
  },
  validators: {
    ...createOpenAICompatibleValidators({
      checks: [ProviderValidationCheck.Connectivity, ProviderValidationCheck.ChatCompletions],
    }),
  },
})

export const providerMinimaxGlobal = defineProvider<MinimaxGlobalConfig>({
  id: 'minimax-global',
  name: 'MiniMax Global',
  nameLocalize: ({ t }) => t('settings.pages.providers.provider.minimax-global.title'),
  description: 'minimax.io',
  descriptionLocalize: ({ t }) => t('settings.pages.providers.provider.minimax-global.description'),
  tasks: ['chat'],
  icon: 'i-lobe-icons:minimax',
  iconColor: 'i-lobe-icons:minimax-color',

  createProviderConfig: ({ t }) => minimaxGlobalConfigSchema.extend({
    apiKey: minimaxGlobalConfigSchema.shape.apiKey.meta({
      labelLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.label'),
      descriptionLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.description'),
      placeholderLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.api-key.placeholder'),
      type: 'password',
    }),
    baseUrl: minimaxGlobalConfigSchema.shape.baseUrl.meta({
      labelLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.label'),
      descriptionLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.description'),
      placeholderLocalized: t('settings.pages.providers.catalog.edit.config.common.fields.field.base-url.placeholder'),
    }),
  }),
  createProvider(config) {
    return withMinimaxKeyRotation(createMinimax(config.apiKey, config.baseUrl), config.apiKey)
  },

  extraMethods: {
    listModels: async () => minimaxModels.map(m => ({ ...m, provider: 'minimax-global' })),
  },
  validationRequiredWhen(config) {
    return !!config.apiKey?.trim()
  },
  validators: {
    ...createOpenAICompatibleValidators({
      checks: [ProviderValidationCheck.Connectivity, ProviderValidationCheck.ChatCompletions],
    }),
  },
})
