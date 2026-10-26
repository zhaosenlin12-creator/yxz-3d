import { describe, expect, it } from 'vitest'

import {
  isAbortLikeError,
  isFailoverEligibleError,
  parseProviderFallbackConfig,
  resolveFallbackCandidates,
} from './llm'

describe('stores/llm fallback helpers', () => {
  it('parses fallback config and removes invalid or duplicate candidates', () => {
    const parsed = parseProviderFallbackConfig(JSON.stringify({
      consciousness: {
        cooldownMs: 1234,
        candidates: [
          { providerId: 'deepseek', model: 'deepseek-chat' },
          { providerId: 'deepseek', model: 'deepseek-chat' },
          { providerId: '', model: 'ignored' },
          { providerId: 'openai-compatible', model: '' },
        ],
      },
    }))

    expect(parsed).toEqual({
      consciousness: {
        cooldownMs: 1234,
        candidates: [
          { providerId: 'deepseek', model: 'deepseek-chat' },
        ],
      },
      vision: undefined,
    })
  })

  it('resolves scoped fallback candidates and strips the active provider/model duplicate', () => {
    const resolved = resolveFallbackCandidates({
      providerId: 'deepseek',
      model: 'deepseek-chat',
      scope: 'consciousness',
      fallbackConfig: {
        consciousness: {
          cooldownMs: 4321,
          candidates: [
            { providerId: 'deepseek', model: 'deepseek-chat' },
            { providerId: 'openai-compatible', model: 'qwen3-max' },
          ],
        },
      },
    })

    expect(resolved.cooldownMs).toBe(4321)
    expect(resolved.candidates).toEqual([
      { providerId: 'openai-compatible', model: 'qwen3-max' },
    ])
  })

  it('treats abort signals and AbortError-like exceptions as non-failover', () => {
    const controller = new AbortController()
    controller.abort()

    expect(isAbortLikeError(new Error('ignored'), controller.signal)).toBe(true)
    expect(isAbortLikeError(Object.assign(new Error('aborted'), { name: 'AbortError' }))).toBe(true)
    expect(isFailoverEligibleError(new Error('aborted by user'), controller.signal)).toBe(false)
  })

  it('does not fail over for prompt-size or moderation errors', () => {
    expect(isFailoverEligibleError(new Error('Prompt too long for maximum context length'))).toBe(false)
    expect(isFailoverEligibleError(new Error('Content policy violation detected'))).toBe(false)
  })

  it('allows failover for provider-side availability failures', () => {
    expect(isFailoverEligibleError(new Error('Server error: HTTP 503'))).toBe(true)
    expect(isFailoverEligibleError(new Error('Invalid API key'))).toBe(true)
    expect(isFailoverEligibleError(new Error('fetch failed'))).toBe(true)
  })
})
