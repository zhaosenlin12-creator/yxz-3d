import { describe, expect, it, vi } from 'vitest'

import { CHAT_SEND_MAX_TURN_MS, CHAT_SEND_TIMEOUT_MS, ChatSendTimeoutError, withChatSendTimeout } from './chat-send-recovery'

describe('chat send watchdog', () => {
  it('gives up on a turn that stays silent', async () => {
    vi.useFakeTimers()
    try {
      const onTimeout = vi.fn()
      const operation = new Promise<string>(() => {})
      const pending = withChatSendTimeout(operation, onTimeout)
      const assertion = expect(pending).rejects.toBeInstanceOf(ChatSendTimeoutError)

      await vi.advanceTimersByTimeAsync(CHAT_SEND_TIMEOUT_MS + 5_000)
      await assertion
      expect(onTimeout).toHaveBeenCalledTimes(1)
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('keeps a busy turn alive even when it says nothing', async () => {
    vi.useFakeTimers()
    try {
      const onTimeout = vi.fn()
      let busy = true
      const operation = new Promise<string>(() => {})
      const pending = withChatSendTimeout(operation, onTimeout, () => 'same', {
        isTurnActive: () => busy,
      })
      // The handler has to be attached before the clock moves, otherwise the
      // rejection lands in the microtask queue without a listener.
      const settled = pending.then(() => undefined, error => error)

      await vi.advanceTimersByTimeAsync(CHAT_SEND_TIMEOUT_MS + 5_000)
      expect(onTimeout).not.toHaveBeenCalled()

      busy = false
      await vi.advanceTimersByTimeAsync(CHAT_SEND_TIMEOUT_MS + 5_000)
      expect(await settled).toBeInstanceOf(ChatSendTimeoutError)
      expect(onTimeout).toHaveBeenCalledTimes(1)
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('treats a changing progress stamp as a live turn', async () => {
    vi.useFakeTimers()
    try {
      const onTimeout = vi.fn()
      let stamp = 0
      const operation = new Promise<string>(() => {})
      const pending = withChatSendTimeout(operation, onTimeout, () => stamp)
      const settled = pending.then(() => undefined, error => error)
      const ticker = setInterval(() => {
        stamp++
      }, 5_000)

      await vi.advanceTimersByTimeAsync(CHAT_SEND_TIMEOUT_MS + 5_000)
      expect(onTimeout).not.toHaveBeenCalled()

      clearInterval(ticker)
      await vi.advanceTimersByTimeAsync(CHAT_SEND_TIMEOUT_MS + 5_000)
      expect(await settled).toBeInstanceOf(ChatSendTimeoutError)
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('stops a turn that never ends, even while it keeps making noise', async () => {
    vi.useFakeTimers()
    try {
      const onTimeout = vi.fn()
      let stamp = 0
      const operation = new Promise<string>(() => {})
      const pending = withChatSendTimeout(operation, onTimeout, () => stamp, {
        isTurnActive: () => true,
        maxTurnMs: 10_000,
      })
      const assertion = expect(pending).rejects.toBeInstanceOf(ChatSendTimeoutError)
      const ticker = setInterval(() => {
        stamp++
      }, 1_000)

      await vi.advanceTimersByTimeAsync(15_000)
      await assertion
      clearInterval(ticker)
      expect(onTimeout).toHaveBeenCalledTimes(1)
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('has a ceiling for a single turn', () => {
    expect(CHAT_SEND_MAX_TURN_MS).toBeGreaterThan(CHAT_SEND_TIMEOUT_MS)
  })
})
