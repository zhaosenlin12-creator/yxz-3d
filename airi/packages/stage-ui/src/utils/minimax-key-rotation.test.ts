import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  countMinimaxDeadKeys,
  createMinimaxKeyRotatingFetch,
  isMinimaxKeyDead,
  markMinimaxKeyDead,
  resetMinimaxDeadKeys,
} from './minimax-key-rotation'

afterEach(() => {
  resetMinimaxDeadKeys()
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

  it('forgets the bench when every key is benched, so a topped-up plan works again', async () => {
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

    // Nothing is benched any more -> both keys are tried once more, and the
    // key that still refuses gets benched again.
    await rotating('https://api.minimaxi.com/v1/chat/completions')
    expect(calls).toEqual(['spent', 'good'])
    expect(isMinimaxKeyDead('good')).toBe(false)
    expect(isMinimaxKeyDead('spent')).toBe(true)
  })
})
