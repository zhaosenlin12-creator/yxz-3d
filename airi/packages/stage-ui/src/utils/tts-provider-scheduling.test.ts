import { describe, expect, it, vi } from 'vitest'

import { createTtsBudgetSignal, isTtsQuotaMessage, TtsProviderScheduler } from './tts-provider-scheduling'

describe('tts provider scheduling', () => {
  it('gives an unmeasured provider the default budget', () => {
    const scheduler = new TtsProviderScheduler()
    expect(scheduler.budgetFor('voicebox-local')).toBe(8_000)
    expect(scheduler.isSkipped('voicebox-local')).toBe(false)
  })

  it('learns the speed of a provider from what it managed', () => {
    const scheduler = new TtsProviderScheduler()
    scheduler.recordSuccess('edge-tts-free', 2_000)
    // Some slack over the measured time, but never below the floor.
    expect(scheduler.budgetFor('edge-tts-free')).toBe(5_000)

    scheduler.recordSuccess('edge-tts-free', 1_000)
    // The average moves towards the new measurement (2000*0.6 + 1000*0.4).
    expect(scheduler.budgetFor('edge-tts-free')).toBe(5_000)
  })

  it('never hands a provider an unbounded amount of time', () => {
    const scheduler = new TtsProviderScheduler()
    scheduler.recordSuccess('slow', 120_000)
    expect(scheduler.budgetFor('slow')).toBe(20_000)
  })

  it('benches a provider that could not answer in time', () => {
    const scheduler = new TtsProviderScheduler()
    scheduler.recordTimeout('voicebox-local')
    expect(scheduler.isSkipped('voicebox-local')).toBe(true)
    // A provider that was too slow keeps the smallest budget.
    expect(scheduler.budgetFor('voicebox-local')).toBe(5_000)
    // The bench expires on its own.
    expect(scheduler.isSkipped('voicebox-local', Date.now() + 5 * 60_000 + 1_000)).toBe(false)
  })

  it('keeps a failed provider out longer when it ran out of credit', () => {
    const scheduler = new TtsProviderScheduler()
    scheduler.recordFailure('minimax-audio-speech', 'insufficient balance')
    expect(scheduler.isSkipped('minimax-audio-speech')).toBe(true)
    expect(scheduler.isSkipped('minimax-audio-speech', Date.now() + 5 * 60_000)).toBe(true)

    const other = new TtsProviderScheduler()
    other.recordFailure('minimax-audio-speech', 'connection reset')
    expect(other.isSkipped('minimax-audio-speech', Date.now() + 90_000)).toBe(false)
  })

  it('recognises the different ways an exhausted balance is reported', () => {
    expect(isTtsQuotaMessage('insufficient balance')).toBe(true)
    expect(isTtsQuotaMessage('余额不足')).toBe(true)
    expect(isTtsQuotaMessage('has reached the Token Plan limit')).toBe(true)
    expect(isTtsQuotaMessage('connection reset')).toBe(false)
    expect(isTtsQuotaMessage(undefined)).toBe(false)
  })

  it('lets a provider that answered in time come back', () => {
    const scheduler = new TtsProviderScheduler()
    scheduler.recordFailure('edge-tts-free', 'temporary glitch')
    expect(scheduler.isSkipped('edge-tts-free')).toBe(true)
    scheduler.recordSuccess('edge-tts-free', 2_000)
    expect(scheduler.isSkipped('edge-tts-free')).toBe(false)
  })
})

describe('tts budget signal', () => {
  it('fires when the budget runs out', async () => {
    vi.useFakeTimers()
    const { signal, dispose } = createTtsBudgetSignal(undefined, 1_000)
    expect(signal.aborted).toBe(false)
    vi.advanceTimersByTime(1_100)
    expect(signal.aborted).toBe(true)
    dispose()
    vi.useRealTimers()
  })

  it('follows the caller when the caller aborts', () => {
    const outer = new AbortController()
    const { signal, dispose } = createTtsBudgetSignal(outer.signal, 10_000)
    expect(signal.aborted).toBe(false)
    outer.abort()
    expect(signal.aborted).toBe(true)
    dispose()
  })

  it('is aborted right away when the caller is already aborted', () => {
    const outer = new AbortController()
    outer.abort()
    const { signal, dispose } = createTtsBudgetSignal(outer.signal, 10_000)
    expect(signal.aborted).toBe(true)
    dispose()
  })

  it('stops the timer when it is disposed', () => {
    vi.useFakeTimers()
    const { signal, dispose } = createTtsBudgetSignal(undefined, 1_000)
    dispose()
    vi.advanceTimersByTime(2_000)
    expect(signal.aborted).toBe(false)
    vi.useRealTimers()
  })
})
