type Primitive = string | number | boolean

interface BootstrapAiriCard {
  name: string
  version: string
  description?: string
  creator?: string
  personality?: string
  scenario?: string
  greetings?: string[]
  systemPrompt?: string
  postHistoryInstructions?: string
  messageExample?: (`{{char}}: ${string}` | `{{user}}: ${string}`)[][]
  extensions?: Record<string, unknown>
}

interface ModuleSelection {
  activeProvider?: string
  activeModel?: string
  voice?: string
  language?: string
  autoSendEnabled?: boolean
  autoSendDelay?: number
}

interface FallbackCandidateSelection {
  providerId: string
  model: string
}

interface FallbackScopeConfig {
  cooldownMs?: number
  candidates?: FallbackCandidateSelection[]
}

interface LocalProviderFallbackConfig {
  consciousness?: FallbackScopeConfig
  vision?: FallbackScopeConfig
}

interface LocalProviderBootstrapConfig {
  revision: string
  providers?: Record<string, Record<string, unknown>>
  addedProviders?: string[]
  cards?: Record<string, BootstrapAiriCard>
  activeCardId?: string
  modules?: {
    consciousness?: ModuleSelection
    vision?: ModuleSelection
    hearing?: ModuleSelection
    speech?: ModuleSelection
  }
  fallbacks?: LocalProviderFallbackConfig
}

const STORAGE_KEYS = {
  revision: 'airi/local-provider-bootstrap/revision',
  providers: 'settings/credentials/providers',
  addedProviders: 'settings/providers/added',
  cards: 'airi-cards',
  activeCardId: 'airi-card-active-id',
  fallbackConfig: 'airi/provider-fallback/config',
  consciousnessActiveProvider: 'settings/consciousness/active-provider',
  consciousnessActiveModel: 'settings/consciousness/active-model',
  visionActiveProvider: 'settings/vision/active-provider',
  visionActiveModel: 'settings/vision/active-model',
  hearingActiveProvider: 'settings/hearing/active-provider',
  hearingActiveModel: 'settings/hearing/active-model',
  hearingAutoSendEnabled: 'settings/hearing/auto-send-enabled',
  hearingAutoSendDelay: 'settings/hearing/auto-send-delay',
  speechActiveProvider: 'settings/speech/active-provider',
  speechActiveModel: 'settings/speech/active-model',
  speechVoice: 'settings/speech/voice',
  speechLanguage: 'settings/speech/language',
} as const

const DEFAULT_FALLBACK_COOLDOWN_MS = 5 * 60 * 1000

function parseJsonObject<T extends object>(raw: string | null, fallback: T): T {
  if (!raw)
    return fallback

  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
      return parsed as T
  }
  catch {
    // Ignore malformed local data and fall back to the provided default.
  }

  return fallback
}

function setPrimitiveStorage(key: string, value: Primitive | undefined) {
  if (value === undefined)
    return

  localStorage.setItem(key, String(value))
}

function normalizeFallbackCandidates(candidates: FallbackCandidateSelection[] | undefined) {
  if (!candidates?.length)
    return []

  const seen = new Set<string>()
  const normalized: FallbackCandidateSelection[] = []

  for (const candidate of candidates) {
    const providerId = String(candidate?.providerId ?? '').trim()
    const model = String(candidate?.model ?? '').trim()
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

function hasFallbackConfig(config: LocalProviderFallbackConfig) {
  return Object.values(config).some(scope => !!scope?.candidates?.length)
}

function createFallbackScope(candidates: FallbackCandidateSelection[] | undefined): FallbackScopeConfig | undefined {
  const normalized = normalizeFallbackCandidates(candidates)
  if (!normalized.length)
    return undefined

  return {
    cooldownMs: DEFAULT_FALLBACK_COOLDOWN_MS,
    candidates: normalized,
  }
}

function buildDefaultFallbackConfig(config: LocalProviderBootstrapConfig): LocalProviderFallbackConfig {
  const providers = config.providers ?? {}
  const consciousnessProvider = config.modules?.consciousness?.activeProvider
  const visionProvider = config.modules?.vision?.activeProvider

  return {
    consciousness: createFallbackScope([
      ...(providers.deepseek && consciousnessProvider !== 'deepseek'
        ? [{ providerId: 'deepseek', model: 'deepseek-chat' }]
        : []),
      ...(providers['openai-compatible'] && consciousnessProvider !== 'openai-compatible'
        ? [{ providerId: 'openai-compatible', model: 'qwen3-max' }]
        : []),
    ]),
    vision: createFallbackScope((providers['openai-compatible'] && visionProvider !== 'openai-compatible'
      ? [{ providerId: 'openai-compatible', model: 'qwen3-vl-flash-2026-01-22' }]
      : [])),
  }
}

function resolveFallbackConfig(config: LocalProviderBootstrapConfig): LocalProviderFallbackConfig {
  const source = config.fallbacks ?? buildDefaultFallbackConfig(config)

  return {
    consciousness: source.consciousness
      ? {
          cooldownMs: source.consciousness.cooldownMs ?? DEFAULT_FALLBACK_COOLDOWN_MS,
          candidates: normalizeFallbackCandidates(source.consciousness.candidates),
        }
      : undefined,
    vision: source.vision
      ? {
          cooldownMs: source.vision.cooldownMs ?? DEFAULT_FALLBACK_COOLDOWN_MS,
          candidates: normalizeFallbackCandidates(source.vision.candidates),
        }
      : undefined,
  }
}

function decodeBootstrapConfig(encoded: string): LocalProviderBootstrapConfig | null {
  try {
    const raw = atob(encoded)
    const parsed = JSON.parse(raw) as LocalProviderBootstrapConfig
    if (!parsed || typeof parsed !== 'object' || !parsed.revision)
      return null

    return parsed
  }
  catch (error) {
    console.error('[airi] Failed to decode local provider bootstrap config.', error)
    return null
  }
}

export function applyLocalProviderBootstrap() {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined')
    return

  const encoded = import.meta.env.VITE_LOCAL_PROVIDER_BOOTSTRAP_B64
  if (!encoded)
    return

  const config = decodeBootstrapConfig(encoded)
  if (!config)
    return

  const appliedRevision = localStorage.getItem(STORAGE_KEYS.revision)
  const fallbackConfig = resolveFallbackConfig(config)
  const existingFallbackConfig = parseJsonObject<LocalProviderFallbackConfig>(
    localStorage.getItem(STORAGE_KEYS.fallbackConfig),
    {},
  )
  const shouldApplyAll = appliedRevision !== config.revision
  const shouldApplyFallback = shouldApplyAll || !hasFallbackConfig(existingFallbackConfig)

  if (!shouldApplyAll && !shouldApplyFallback)
    return

  if (shouldApplyAll) {
    const mergedProviders = {
      ...parseJsonObject<Record<string, Record<string, unknown>>>(localStorage.getItem(STORAGE_KEYS.providers), {}),
      ...config.providers,
    }
    localStorage.setItem(STORAGE_KEYS.providers, JSON.stringify(mergedProviders))

    const addedProviders = parseJsonObject<Record<string, boolean>>(localStorage.getItem(STORAGE_KEYS.addedProviders), {})
    for (const providerId of config.addedProviders ?? []) {
      addedProviders[providerId] = true
    }
    localStorage.setItem(STORAGE_KEYS.addedProviders, JSON.stringify(addedProviders))

    if (config.cards) {
      const existingCards = parseJsonObject<Record<string, BootstrapAiriCard>>(localStorage.getItem(STORAGE_KEYS.cards), {})
      localStorage.setItem(STORAGE_KEYS.cards, JSON.stringify({
        ...existingCards,
        ...config.cards,
      }))
    }
    setPrimitiveStorage(STORAGE_KEYS.activeCardId, config.activeCardId)

    const consciousness = config.modules?.consciousness
    setPrimitiveStorage(STORAGE_KEYS.consciousnessActiveProvider, consciousness?.activeProvider)
    setPrimitiveStorage(STORAGE_KEYS.consciousnessActiveModel, consciousness?.activeModel)

    const vision = config.modules?.vision
    setPrimitiveStorage(STORAGE_KEYS.visionActiveProvider, vision?.activeProvider)
    setPrimitiveStorage(STORAGE_KEYS.visionActiveModel, vision?.activeModel)

    const hearing = config.modules?.hearing
    setPrimitiveStorage(STORAGE_KEYS.hearingActiveProvider, hearing?.activeProvider)
    setPrimitiveStorage(STORAGE_KEYS.hearingActiveModel, hearing?.activeModel)
    setPrimitiveStorage(STORAGE_KEYS.hearingAutoSendEnabled, hearing?.autoSendEnabled)
    setPrimitiveStorage(STORAGE_KEYS.hearingAutoSendDelay, hearing?.autoSendDelay)

    const speech = config.modules?.speech
    setPrimitiveStorage(STORAGE_KEYS.speechActiveProvider, speech?.activeProvider)
    setPrimitiveStorage(STORAGE_KEYS.speechActiveModel, speech?.activeModel)
    setPrimitiveStorage(STORAGE_KEYS.speechVoice, speech?.voice)
    setPrimitiveStorage(STORAGE_KEYS.speechLanguage, speech?.language)
  }

  if (shouldApplyFallback && hasFallbackConfig(fallbackConfig)) {
    localStorage.setItem(STORAGE_KEYS.fallbackConfig, JSON.stringify(fallbackConfig))
    console.info('[airi] Applied local provider fallback bootstrap.')
  }

  if (shouldApplyAll) {
    localStorage.setItem(STORAGE_KEYS.revision, config.revision)
    console.info(`[airi] Applied local provider bootstrap revision: ${config.revision}`)
  }
}
