import { useConsciousnessStore } from '../stores/modules/consciousness'
import { useProvidersStore } from '../stores/providers'

export interface ProviderSeedFile {
  providers?: Record<string, Record<string, unknown>>
  activeProvider?: string
  activeModel?: string
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
    for (const [key, value] of Object.entries(existing)) {
      if (value !== '' && value !== null && value !== undefined)
        merged[key] = value
    }

    if (JSON.stringify(merged) !== JSON.stringify(existing)) {
      providersStore.providers[providerId] = merged
      applied.push(providerId)
    }

    providersStore.markProviderAdded(providerId)
  }

  if (seed.activeProvider && !consciousnessStore.activeProvider && applied.includes(seed.activeProvider))
    consciousnessStore.activeProvider = seed.activeProvider

  if (seed.activeModel && !consciousnessStore.activeModel && applied.includes(consciousnessStore.activeProvider))
    consciousnessStore.activeModel = seed.activeModel

  return { applied, skipped }
}

export async function applyProviderSeedFromFile(url?: string): Promise<ProviderSeedResult> {
  const seed = await loadProviderSeed(url)
  if (!seed)
    return { applied: [], skipped: [] }

  return applyProviderSeed(seed)
}
