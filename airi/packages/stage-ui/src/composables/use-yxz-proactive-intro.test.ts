import { describe, expect, it } from 'vitest'

import { YXZ_PROACTIVE_INTRO_ID, YXZ_PROACTIVE_INTRO_TEXT, ensureYXZProactiveIntro } from './use-yxz-proactive-intro'

describe('YXZ proactive intro', () => {
  it('adds one actionable introduction to an empty session', () => {
    const result = ensureYXZProactiveIntro([], 123)

    expect(result.added).toBe(true)
    expect(result.messages).toHaveLength(1)
    expect(result.messages[0]?.id).toBe(YXZ_PROACTIVE_INTRO_ID)
    expect(result.messages[0]?.content).toBe(YXZ_PROACTIVE_INTRO_TEXT)
  })

  it('does not duplicate the introduction after a reload', () => {
    const first = ensureYXZProactiveIntro([], 123)
    const second = ensureYXZProactiveIntro(first.messages, 456)

    expect(second.added).toBe(false)
    expect(second.messages).toBe(first.messages)
  })

  it('refreshes the fixed introduction text when a prior version is stored', () => {
    const prior = ensureYXZProactiveIntro([], 123).messages
    const legacy = [{ ...prior[0], content: '你好，我是宜小智。' }]

    const result = ensureYXZProactiveIntro(legacy, 456)

    expect(result.added).toBe(false)
    expect(result.messages).not.toBe(legacy)
    expect(result.messages[0]?.content).toBe(YXZ_PROACTIVE_INTRO_TEXT)
    expect(result.messages[0]?.createdAt).toBe(123)
  })
})
