import { useConsciousnessStore } from '../stores/modules/consciousness'
import { useSpeechStore } from '../stores/modules/speech'
import { useProvidersStore } from '../stores/providers'

export interface ProviderSeedFile {
  providers?: Record<string, Record<string, unknown>>
  activeProvider?: string
  activeModel?: string
  /**
   * When true the seed is authoritative: its credentials replace whatever the
   * browser still has in localStorage.  Exhibition machines are re-seeded
   * from disk, and a stale key in localStorage would silently win over a
   * rotated one.
   */
  override?: boolean
  /**
   * The speech provider / voice is chosen by hand in the settings, and that
   * choice has to survive a reload. `override` exists to replace stale
   * *credentials* in localStorage with a rotated key, so it must not be
   * allowed to drag the voice back to the seed default. A seed that really
   * wants to move the voice has to ask for it explicitly.
   */
  speechOverride?: boolean
  speech?: {
    provider?: string
    model?: string
    voice?: string
  }
}

export interface ProviderSeedResult {
  applied: string[]
  skipped: string[]
}

const DEFAULT_SEED_URL = '/provider-seed.json'

/**
 * Read the optional local provider seed file.
 *
 * The file lives in `apps/stage-web/public/provider-seed.json` and is
 * git-ignored, so it stays a local secret. When it is absent the app simply
 * behaves like a stock AIRI install and asks for a provider in the UI.
 */
export async function loadProviderSeed(url: string = DEFAULT_SEED_URL): Promise<ProviderSeedFile | null> {
  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok)
      return null

    const payload = await response.json()
    if (!payload || typeof payload !== 'object')
      return null

    return payload as ProviderSeedFile
  }
  catch {
    return null
  }
}

/**
 * Apply the seed to the provider store.
 *
 * AIRI initializes every provider with a default config (baseUrl and
 * friends), so "already configured" cannot be decided by "the config object
 * is empty". Fields the user filled in by hand always win; the seed only
 * fills the blanks.
 */
export function applyProviderSeed(seed: ProviderSeedFile): ProviderSeedResult {
  const providersStore = useProvidersStore()
  const consciousnessStore = useConsciousnessStore()
  const applied: string[] = []
  const skipped: string[] = []

  for (const [providerId, config] of Object.entries(seed.providers ?? {})) {
    // Unknown provider ids are ignored: the seed must not invent providers.
    if (!providersStore.getProviderMetadata(providerId)) {
      skipped.push(providerId)
      continue
    }

    const existing = providersStore.getProviderConfig(providerId) ?? {}
    const merged: Record<string, unknown> = { ...config }
    if (!seed.override) {
      // Fields the user filled in by hand always win.
      for (const [key, value] of Object.entries(existing)) {
        if (value !== '' && value !== null && value !== undefined)
          merged[key] = value
      }
    }

    if (JSON.stringify(merged) !== JSON.stringify(existing)) {
      providersStore.providers[providerId] = merged
      applied.push(providerId)
    }

    providersStore.markProviderAdded(providerId)
  }

  const providerReady = seed.override || applied.includes(seed.activeProvider ?? '')
  if (seed.activeProvider && providerReady && (seed.override || !consciousnessStore.activeProvider))
    consciousnessStore.activeProvider = seed.activeProvider

  if (seed.activeModel && providerReady && (seed.override || !consciousnessStore.activeModel))
    consciousnessStore.activeModel = seed.activeModel

  // Speech (TTS) is selected independently from the chat provider, so the
  // seed configures it separately. Only take over when nothing was chosen
  // yet: a hand-picked voice has to survive a restart.
  const speechSeed = seed.speech
  if (speechSeed?.provider) {
    const speechStore = useSpeechStore()
    const currentProvider = speechStore.activeSpeechProvider
    const isUnconfigured = !currentProvider || currentProvider === 'speech-noop'

    if (isUnconfigured || seed.speechOverride) {
      speechStore.activeSpeechProvider = speechSeed.provider
      if (speechSeed.model)
        speechStore.activeSpeechModel = speechSeed.model
      if (speechSeed.voice)
        speechStore.activeSpeechVoiceId = speechSeed.voice
      applied.push(`speech:${speechSeed.provider}`)
    }
    else {
      skipped.push(`speech:${speechSeed.provider}`)
    }
  }

  return { applied, skipped }
}

export async function applyProviderSeedFromFile(url?: string): Promise<ProviderSeedResult> {
  const seed = await loadProviderSeed(url)
  if (!seed)
    return { applied: [], skipped: [] }

  return applyProviderSeed(seed)
}
