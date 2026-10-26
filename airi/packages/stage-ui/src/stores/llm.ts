import type { WebSocketEvents } from '@proj-airi/server-sdk'
import type { ChatProvider } from '@xsai-ext/providers/utils'
import type { CommonContentPart, CompletionToolCall, Message, Tool } from '@xsai/shared-chat'

import { listModels } from '@xsai/model'
import { streamText } from '@xsai/stream-text'
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { createSparkCommandTool, debug, mcp } from '../tools'
import { createYXZCreationTools } from '../tools/yxz-creation'
import { cloneForTransport } from '../utils/clone-for-transport'
import { useModsServerChannelStore } from './mods/api/channel-server'
import { useProvidersStore } from './providers'
import { useSettingsStageModel } from './settings/stage-model'

export type StreamEvent
  = | { type: 'text-delta', text: string }
    | ({ type: 'finish' } & any)
    | ({ type: 'tool-call' } & CompletionToolCall)
    | { type: 'tool-result', toolCallId: string, result?: string | CommonContentPart[] }
    | { type: 'error', error: any }

export interface ProviderFallbackCandidate {
  providerId: string
  model: string
}

export interface ProviderFallbackScopeConfig {
  cooldownMs?: number
  candidates?: ProviderFallbackCandidate[]
}

export interface ProviderFallbackConfig {
  consciousness?: ProviderFallbackScopeConfig
  vision?: ProviderFallbackScopeConfig
}

export interface StreamAttemptInfo {
  providerId?: string
  model: string
  fallback: boolean
  toolsEnabled: boolean
}

export interface StreamOptions {
  abortSignal?: AbortSignal
  headers?: Record<string, string>
  onStreamEvent?: (event: StreamEvent) => void | Promise<void>
  onAttemptStart?: (attempt: StreamAttemptInfo) => void | Promise<void>
  toolsCompatibility?: Map<string, boolean>
  supportsTools?: boolean
  waitForTools?: boolean
  tools?: Tool[] | (() => Promise<Tool[] | undefined>)
  providerId?: string
  scope?: 'consciousness' | 'vision'
}

interface RuntimeCandidate {
  providerId?: string
  model: string
}

const FALLBACK_CONFIG_STORAGE_KEY = 'airi/provider-fallback/config'
const DEFAULT_FALLBACK_COOLDOWN_MS = 5 * 60 * 1000

const NON_FAILOVER_ERROR_PATTERNS: RegExp[] = [
  /context length/i,
  /maximum context/i,
  /prompt.+too long/i,
  /input.+too large/i,
  /content policy/i,
  /safety/i,
  /moderation/i,
]

const ABORT_ERROR_PATTERNS: RegExp[] = [
  /\babort(ed|ing)?\b/i,
  /\bcancel(l)?ed\b/i,
  /\bcancel(l)?ation\b/i,
]

function sanitizeMessages(messages: unknown[]): Message[] {
  return messages.map((m: any) => {
    if (m && m.role === 'error') {
      return {
        role: 'user',
        content: `User encountered error: ${String(m.content ?? '')}`,
      } as Message
    }
    // NOTICE: Flatten array content for providers (e.g. DeepSeek) that expect string,
    // not content-part arrays. Skipped when image_url parts are present.
    if (m && Array.isArray(m.content)) {
      const contentParts = m.content as { type?: string, text?: string }[]
      if (!contentParts.some(p => p?.type === 'image_url')) {
        return { ...m, content: contentParts.map(p => p?.text ?? '').join('') } as Message
      }
    }
    return m as Message
  })
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return !!value
    && typeof value === 'object'
    && !Array.isArray(value)
    && Object.values(value as Record<string, unknown>).every(item => typeof item === 'string')
}

function normalizeFallbackCandidates(candidates: unknown): ProviderFallbackCandidate[] {
  if (!Array.isArray(candidates))
    return []

  const seen = new Set<string>()
  const normalized: ProviderFallbackCandidate[] = []

  for (const candidate of candidates) {
    const providerId = typeof (candidate as ProviderFallbackCandidate | undefined)?.providerId === 'string'
      ? (candidate as ProviderFallbackCandidate).providerId.trim()
      : ''
    const model = typeof (candidate as ProviderFallbackCandidate | undefined)?.model === 'string'
      ? (candidate as ProviderFallbackCandidate).model.trim()
      : ''

    if (!providerId || !model)
      continue

    const key = `${providerId}:${model}`
    if (seen.has(key))
      continue

    seen.add(key)
    normalized.push({ providerId, model })
  }

  return normalized
}

export function parseProviderFallbackConfig(raw: string | null | undefined): ProviderFallbackConfig {
  if (!raw)
    return {}

  try {
    const parsed = JSON.parse(raw) as ProviderFallbackConfig
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      return {}

    return {
      consciousness: parsed.consciousness
        ? {
            cooldownMs: typeof parsed.consciousness.cooldownMs === 'number'
              ? parsed.consciousness.cooldownMs
              : undefined,
            candidates: normalizeFallbackCandidates(parsed.consciousness.candidates),
          }
        : undefined,
      vision: parsed.vision
        ? {
            cooldownMs: typeof parsed.vision.cooldownMs === 'number'
              ? parsed.vision.cooldownMs
              : undefined,
            candidates: normalizeFallbackCandidates(parsed.vision.candidates),
          }
        : undefined,
    }
  }
  catch {
    return {}
  }
}

function readProviderFallbackConfig(): ProviderFallbackConfig {
  if (typeof localStorage === 'undefined')
    return {}

  return parseProviderFallbackConfig(localStorage.getItem(FALLBACK_CONFIG_STORAGE_KEY))
}

export function resolveFallbackCandidates(input: {
  providerId?: string
  model: string
  scope?: StreamOptions['scope']
  fallbackConfig?: ProviderFallbackConfig
}) {
  const fallbackConfig = input.fallbackConfig ?? readProviderFallbackConfig()
  const scopeConfig = input.scope ? fallbackConfig[input.scope] : undefined
  const cooldownMs = scopeConfig?.cooldownMs ?? DEFAULT_FALLBACK_COOLDOWN_MS
  const candidates = normalizeFallbackCandidates(scopeConfig?.candidates)
    .filter(candidate => candidate.providerId !== input.providerId || candidate.model !== input.model)

  return {
    cooldownMs,
    candidates,
  }
}

function formatCandidateLabel(candidate: RuntimeCandidate) {
  return candidate.providerId
    ? `${candidate.providerId}:${candidate.model}`
    : candidate.model
}

function getCandidateStorageKey(candidate: RuntimeCandidate) {
  if (!candidate.providerId)
    return null
  return `${candidate.providerId}:${candidate.model}`
}

export function isAbortLikeError(err: unknown, abortSignal?: AbortSignal) {
  if (abortSignal?.aborted)
    return true

  const maybeError = err as { name?: unknown, code?: unknown } | undefined
  if (maybeError?.name === 'AbortError' || maybeError?.code === 'ABORT_ERR')
    return true
  if (typeof DOMException !== 'undefined' && err instanceof DOMException && err.name === 'AbortError')
    return true

  const msg = String(err)
  return ABORT_ERROR_PATTERNS.some(pattern => pattern.test(msg))
}

export function isFailoverEligibleError(err: unknown, abortSignal?: AbortSignal) {
  if (isAbortLikeError(err, abortSignal))
    return false

  const msg = String(err)
  return !NON_FAILOVER_ERROR_PATTERNS.some(pattern => pattern.test(msg))
}

function streamOptionsToolsCompatibilityOk(model: string, chatProvider: ChatProvider, _: Message[], options?: StreamOptions): boolean {
  const key = `${chatProvider.chat(model).baseURL}-${model}`
  if (options?.toolsCompatibility?.get(key) === false)
    return false
  if (options?.supportsTools)
    return true
  return true
}

async function streamFrom(model: string, chatProvider: ChatProvider, messages: Message[], sendSparkCommand: (command: WebSocketEvents['spark:command']) => void, options?: StreamOptions) {
  const chatConfig = chatProvider.chat(model)
  // @xsai/stream-text clones `messages` before opening the request. Keep the
  // final provider payload strictly cloneable because context/tool integrations
  // can leave behind DOM, function, or circular values in a prior turn.
  const sanitized = cloneForTransport(sanitizeMessages(messages as unknown[])) as Message[]

  const resolveTools = async () => {
    const tools = typeof options?.tools === 'function'
      ? await options.tools()
      : options?.tools
    return tools ?? []
  }

  const supportedTools = streamOptionsToolsCompatibilityOk(model, chatProvider, messages, options)
  const isYXZPreset = useSettingsStageModel().stageModelSelected === 'preset-yxz'
  const tools = supportedTools
    ? [
        // The exhibition preset owns its creation tools. Generic MCP/debug
        // tools are intentionally not exposed here: leaking them produces
        // technical names such as builtIn_mcpCallTool in visitor-facing chat.
        ...(isYXZPreset ? [] : await mcp()),
        ...(isYXZPreset ? [] : await debug()),
        ...await resolveTools(),
        ...(isYXZPreset ? await createYXZCreationTools() : []),
        ...(isYXZPreset ? [] : [await createSparkCommandTool({ sendSparkCommand })]),
      ]
    : undefined

  return new Promise<void>((resolve, reject) => {
    let settled = false
    const resolveOnce = () => {
      if (settled)
        return
      settled = true
      resolve()
    }
    const rejectOnce = (err: unknown) => {
      if (settled)
        return
      settled = true
      reject(err)
    }

    const onEvent = async (event: unknown) => {
      try {
        await options?.onStreamEvent?.(event as StreamEvent)
        if (event && (event as StreamEvent).type === 'finish') {
          const finishReason = (event as any).finishReason
          if (finishReason !== 'tool_calls' || !options?.waitForTools)
            resolveOnce()
        }
        else if (event && (event as StreamEvent).type === 'error') {
          rejectOnce((event as any).error ?? new Error('Stream error'))
        }
      }
      catch (err) {
        rejectOnce(err)
      }
    }

    try {
      const streamResult = streamText({
        ...chatConfig,
        abortSignal: options?.abortSignal,
        maxSteps: 10,
        messages: sanitized,
        headers: options?.headers,
        tools,
        onEvent,
      })

      // NOTICE: Consume underlying promises to prevent unhandled rejections from
      // @xsai/stream-text's SSE parser surfacing as faulted app state.
      void streamResult.steps.catch((err) => {
        rejectOnce(err)
        console.error('Stream steps error:', err)
      })
      void streamResult.messages.catch(err => console.error('Stream messages error:', err))
      void streamResult.usage.catch(err => console.error('Stream usage error:', err))
      void streamResult.totalUsage.catch(err => console.error('Stream totalUsage error:', err))
    }
    catch (err) {
      rejectOnce(err)
    }
  })
}

// Runtime auto-degrade: patterns that indicate the model/provider does not support tool calling.
const TOOLS_RELATED_ERROR_PATTERNS: RegExp[] = [
  /does not support tools/i, // Ollama
  /no endpoints found that support tool use/i, // OpenRouter
  /invalid schema for function/i, // OpenAI-compatible
  /invalid.?function.?parameters/i, // OpenAI-compatible
  /functions are not supported/i, // Azure AI Foundry
  /unrecognized request argument.+tools/i, // Azure AI Foundry
  /tool use with function calling is unsupported/i, // Google Generative AI
  /tool_use_failed/i, // Groq
  /does not support function.?calling/i, // Anthropic
  /tools?\s+(is|are)\s+not\s+supported/i, // Cloudflare Workers AI
]

export function isToolRelatedError(err: unknown): boolean {
  const msg = String(err)
  return TOOLS_RELATED_ERROR_PATTERNS.some(p => p.test(msg))
}

export const useLLM = defineStore('llm', () => {
  const toolsCompatibility = ref<Map<string, boolean>>(new Map())
  const failoverCooldowns = ref<Map<string, number>>(new Map())
  const modsServerChannelStore = useModsServerChannelStore()
  const providersStore = useProvidersStore()

  function modelKey(model: string, chatProvider: ChatProvider): string {
    return `${chatProvider.chat(model).baseURL}-${model}`
  }

  function isSubstantiveStreamEvent(event: StreamEvent) {
    return event.type === 'text-delta'
      || event.type === 'tool-call'
      || event.type === 'tool-result'
  }

  function clearCandidateCooldown(candidate: RuntimeCandidate) {
    const key = getCandidateStorageKey(candidate)
    if (!key)
      return

    failoverCooldowns.value.delete(key)
  }

  function markCandidateCooldown(candidate: RuntimeCandidate, cooldownMs: number, err: unknown) {
    const key = getCandidateStorageKey(candidate)
    if (!key || cooldownMs <= 0)
      return

    const until = Date.now() + cooldownMs
    failoverCooldowns.value.set(key, until)
    console.warn(`[llm] Cooling down "${formatCandidateLabel(candidate)}" for ${cooldownMs}ms due to:`, err)
  }

  function isCandidateCoolingDown(candidate: RuntimeCandidate) {
    const key = getCandidateStorageKey(candidate)
    if (!key)
      return false

    const until = failoverCooldowns.value.get(key)
    if (!until)
      return false

    if (until <= Date.now()) {
      failoverCooldowns.value.delete(key)
      return false
    }

    return true
  }

  function hasNonCoolingCandidateAfter(candidates: RuntimeCandidate[], fromIndex: number) {
    return candidates.slice(fromIndex + 1).some(candidate => !isCandidateCoolingDown(candidate))
  }

  function getHeadersForCandidate(candidate: RuntimeCandidate, explicitHeaders: Record<string, string> | undefined, primaryProviderId?: string) {
    if (!candidate.providerId || candidate.providerId === primaryProviderId)
      return explicitHeaders

    const providerConfig = providersStore.getProviderConfig(candidate.providerId) as { headers?: unknown } | undefined
    return isStringRecord(providerConfig?.headers)
      ? providerConfig.headers
      : undefined
  }

  async function resolveChatProvider(candidate: RuntimeCandidate, primaryChatProvider: ChatProvider, primaryProviderId?: string) {
    if (!candidate.providerId || candidate.providerId === primaryProviderId)
      return primaryChatProvider

    return await providersStore.getProviderInstance<ChatProvider>(candidate.providerId)
  }

  async function runCandidateStream(
    candidate: RuntimeCandidate,
    primaryModel: string,
    primaryChatProvider: ChatProvider,
    primaryProviderId: string | undefined,
    messages: Message[],
    options: StreamOptions | undefined,
  ) {
    const chatProvider = await resolveChatProvider(candidate, primaryChatProvider, primaryProviderId)
    const key = modelKey(candidate.model, chatProvider)
    const attemptOptions: StreamOptions = {
      ...options,
      headers: getHeadersForCandidate(candidate, options?.headers, primaryProviderId),
      toolsCompatibility: toolsCompatibility.value,
    }

    let emittedOutput = false
    const emitAttemptStart = async () => {
      const toolsEnabled = streamOptionsToolsCompatibilityOk(candidate.model, chatProvider, messages, attemptOptions)
      await options?.onAttemptStart?.({
        providerId: candidate.providerId,
        model: candidate.model,
        fallback: candidate.providerId !== primaryProviderId || candidate.model !== primaryModel,
        toolsEnabled,
      })
    }

    const execute = async () => {
      await emitAttemptStart()
      try {
        await streamFrom(
          candidate.model,
          chatProvider,
          messages,
          // TODO(@nekomeowww,@shinohara-rin): we should not register the command callback on every stream anyway...
          (command) => {
            // TODO(@nekomeowww): instruct the LLM to understand what destination is.
            // Currently without skill like prompt injection, many issues occur.
            // destination mostly are wrong or hallucinated, we need to find a way to make it more reliable.
            //
            // For now, since destinations as array will always broadcast to all connected modules/agents, we can set it to
            // empty array to avoid wrong routing.
            command.destinations = []

            modsServerChannelStore.send({
              type: 'spark:command',
              data: command,
            })
          },
          {
            ...attemptOptions,
            onStreamEvent: async (event) => {
              if (isSubstantiveStreamEvent(event))
                emittedOutput = true
              await options?.onStreamEvent?.(event)
            },
          },
        )
        return undefined
      }
      catch (error) {
        return error
      }
    }

    let error = await execute()
    const toolsEnabled = streamOptionsToolsCompatibilityOk(candidate.model, chatProvider, messages, attemptOptions)

    if (error && isToolRelatedError(error) && toolsEnabled && !emittedOutput) {
      console.warn(`[llm] Auto-disabling tools for "${key}" due to tool-related error`)
      toolsCompatibility.value.set(key, false)
      emittedOutput = false
      error = await execute()
    }

    if (!error) {
      clearCandidateCooldown(candidate)
    }

    return {
      error,
      emittedOutput,
    }
  }

  async function stream(model: string, chatProvider: ChatProvider, messages: Message[], options?: StreamOptions) {
    const failover = resolveFallbackCandidates({
      providerId: options?.providerId,
      model,
      scope: options?.scope,
    })

    const runtimeCandidates: RuntimeCandidate[] = [
      { providerId: options?.providerId, model },
      ...failover.candidates,
    ].filter((candidate, index, candidates) => {
      const key = `${candidate.providerId ?? '__primary__'}:${candidate.model}`
      return candidates.findIndex(other => `${other.providerId ?? '__primary__'}:${other.model}` === key) === index
    })

    let lastError: unknown

    for (const [index, candidate] of runtimeCandidates.entries()) {
      if (isCandidateCoolingDown(candidate) && hasNonCoolingCandidateAfter(runtimeCandidates, index)) {
        console.warn(`[llm] Skipping cooling-down provider "${formatCandidateLabel(candidate)}"`)
        continue
      }

      const { error, emittedOutput } = await runCandidateStream(
        candidate,
        model,
        chatProvider,
        options?.providerId,
        messages,
        options,
      )

      if (!error)
        return

      lastError = error
      const failoverEligible = isFailoverEligibleError(error, options?.abortSignal)
      if (failoverEligible)
        markCandidateCooldown(candidate, failover.cooldownMs, error)

      if (emittedOutput || !failoverEligible || index === runtimeCandidates.length - 1)
        break

      console.warn(
        `[llm] Falling back from "${formatCandidateLabel(candidate)}" to "${formatCandidateLabel(runtimeCandidates[index + 1])}" due to:`,
        error,
      )
    }

    throw lastError ?? new Error('Stream failed')
  }

  async function models(apiUrl: string, apiKey: string) {
    if (apiUrl === '')
      return []

    try {
      return await listModels({
        baseURL: (apiUrl.endsWith('/') ? apiUrl : `${apiUrl}/`) as `${string}/`,
        apiKey,
      })
    }
    catch (err) {
      if (String(err).includes(`Failed to construct 'URL': Invalid URL`))
        return []
      throw err
    }
  }

  return {
    models,
    stream,
  }
})
