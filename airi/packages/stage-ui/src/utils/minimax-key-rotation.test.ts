import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  MINIMAX_DEAD_KEY_COOLDOWN_MS,
  countMinimaxDeadKeys,
  createMinimaxKeyRotatingFetch,
  isMinimaxKeyDead,
  markMinimaxKeyDead,
  resetMinimaxDeadKeys,
} from './minimax-key-rotation'

afterEach(() => {
  resetMinimaxDeadKeys()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('minimax dead key bench', () => {
  it('remembers a benched key until the cooldown is over', () => {
    expect(isMinimaxKeyDead('k1')).toBe(false)
    markMinimaxKeyDead('k1', 60_000)
    expect(isMinimaxKeyDead('k1')).toBe(true)
    expect(countMinimaxDeadKeys()).toBe(1)
    // A key whose bench expired may be tried again.
    expect(isMinimaxKeyDead('k1', Date.now() + 120_000)).toBe(false)
  })

  it('skips a benched key on the next request', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      calls.push(key.replace('Bearer ', ''))
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent', 'good'])
    markMinimaxKeyDead('spent')

    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['good'])
  })

  it('benches a key that answers 429 so the next turn does not repeat it', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      calls.push(key.replace('Bearer ', ''))
      if (key.includes('spent'))
        return new Response('rate limited', { status: 429 })
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent', 'good'])
    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['spent', 'good'])
    expect(isMinimaxKeyDead('spent')).toBe(true)

    // The second turn goes straight to the key that works.
    calls.length = 0
    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['good'])
  })

  it('benches a key whose Token Plan ran out', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      if (key.includes('spent')) {
        return new Response(JSON.stringify({
          base_resp: { status_code: 2056, status_msg: 'has reached the Token Plan limit' },
        }), { status: 200 })
      }
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent', 'good'])
    const response = await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(await response.text()).toBe('ok')
    expect(isMinimaxKeyDead('spent')).toBe(true)
  })

  it('benches a key that answers HTTP 402 (Token Plan exhausted on the OpenAI-compatible endpoint)', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      calls.push(key.replace('Bearer ', ''))
      if (key.includes('spent')) {
        return new Response(JSON.stringify({
          error: { message: 'insufficient balance' },
        }), { status: 402 })
      }
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent', 'good'])
    const response = await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(await response.text()).toBe('ok')
    expect(calls).toEqual(['spent', 'good'])
    expect(isMinimaxKeyDead('spent')).toBe(true)

    // The next turn must not pay for the dead key again.
    calls.length = 0
    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['good'])
  })

  it('reports why a key was benched when every key fails', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      if (key.includes('spent')) {
        return new Response(JSON.stringify({
          error: { message: 'insufficient balance' },
        }), { status: 402 })
      }
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent'])
    await expect(rotating('https://api.minimaxi.com/v1/chat/completions'))
      .rejects.toThrow(/402/)
  })

  it('does not wake a benched key pool up again', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const key = new Headers(init?.headers).get('authorization') ?? ''
      calls.push(key.replace('Bearer ', ''))
      if (key.includes('spent'))
        return new Response('rate limited', { status: 429 })
      return new Response('ok', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rotating = createMinimaxKeyRotatingFetch(['spent', 'good'])
    markMinimaxKeyDead('spent')
    markMinimaxKeyDead('good')
    expect(countMinimaxDeadKeys()).toBe(2)

    // The whole pool is benched, so nothing is dialled at all.  Waking the
    // pool up here used to turn every line of speech into a burst of doomed
    // requests before anything gave up.
    await expect(rotating('https://api.minimaxi.com/v1/chat/completions'))
      .rejects.toThrow(/额度已用尽/)
    expect(calls).toEqual([])

    // The bench expires on its own, so a topped-up plan comes back.
    const later = Date.now() + MINIMAX_DEAD_KEY_COOLDOWN_MS + 1_000
    vi.useFakeTimers()
    vi.setSystemTime(later)
    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['spent', 'good'])
  })
})
