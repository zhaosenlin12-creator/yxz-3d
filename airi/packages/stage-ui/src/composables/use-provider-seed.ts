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
  /**
   * Version of the speech chain (primary + fallbacks) the seed describes.
   *
   * The chain itself is normally the operator's choice and therefore kept
   * across reloads. Bumping the version is how a release moves an existing
   * installation onto a new chain exactly once: the seed wins while the
   * stored version is older, and afterwards hand-picked voices stay put.
   */
  speechChainVersion?: number
  speech?: {
    provider?: string
    model?: string
    voice?: string
    /**
     * Backup speech providers, tried in order when the primary one cannot
     * produce audio.
     */
    fallbacks?: Array<{ providerId: string, model?: string, voice?: string }>
  }
}

export interface ProviderSeedResult {
  applied: string[]
  skipped: string[]
}

const DEFAULT_SEED_URL = '/provider-seed.json'
const SPEECH_CHAIN_VERSION_KEY = 'settings/speech/chain-version'

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
  // A seed that ships a newer chain moves the installation onto it once.
  const seedChainVersion = typeof seed.speechChainVersion === 'number' ? seed.speechChainVersion : 0
  const storedChainVersion = Number(localStorage.getItem(SPEECH_CHAIN_VERSION_KEY) || 0)
  const chainOutdated = seedChainVersion > storedChainVersion

  if (speechSeed?.provider) {
    const speechStore = useSpeechStore()
    const currentProvider = speechStore.activeSpeechProvider
    const isUnconfigured = !currentProvider || currentProvider === 'speech-noop'

    if (isUnconfigured || seed.speechOverride || chainOutdated) {
      speechStore.activeSpeechProvider = speechSeed.provider
      if (speechSeed.model)
        speechStore.activeSpeechModel = speechSeed.model
      if (speechSeed.voice)
        speechStore.activeSpeechVoiceId = speechSeed.voice
      // The voice object belongs to the previous provider: a voice id only
      // means something for the provider it came from.
      speechStore.activeSpeechVoice = undefined
      applied.push(`speech:${speechSeed.provider}`)
    }
    else {
      skipped.push(`speech:${speechSeed.provider}`)
    }
  }

  // The backup chain is separate from the primary provider: an operator may
  // well want a local voice pack first and the cloud API behind it, while
  // the primary provider itself stays the one the user picked.
  if (speechSeed?.fallbacks?.length) {
    const speechStore = useSpeechStore()
    const hasChain = (speechStore.activeSpeechFallbacks ?? []).length > 0

    if (!hasChain || seed.speechOverride || chainOutdated) {
      speechStore.activeSpeechFallbacks = speechSeed.fallbacks
      applied.push(`speech:fallbacks(${speechSeed.fallbacks.length})`)
    }
    else {
      skipped.push('speech:fallbacks')
    }
  }

  if (chainOutdated)
    localStorage.setItem(SPEECH_CHAIN_VERSION_KEY, String(seedChainVersion))

  return { applied, skipped }
}

export async function applyProviderSeedFromFile(url?: string): Promise<ProviderSeedResult> {
  const seed = await loadProviderSeed(url)
  if (!seed)
    return { applied: [], skipped: [] }

  return applyProviderSeed(seed)
}
