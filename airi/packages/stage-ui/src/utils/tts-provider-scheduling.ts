/**
 * Deciding which speech provider gets to answer, and how long it may take.
 *
 * The app is installed on machines that are not alike: a notebook with a
 * GPU renders the local voice pack in two seconds, a desktop without one
 * needs a minute, and a kiosk with neither still has to say something.
 * Nothing here may assume a particular machine -- so the budget a provider
 * gets is derived from how fast that provider actually answered here, and a
 * provider that cannot keep up is simply skipped while the next one in the
 * chain takes over.
 */

export interface TtsProviderSchedulerOptions {
  /** The budget for a provider whose speed has not been measured yet. */
  defaultBudgetMs?: number
  /** A provider never gets less than this, however fast it looked once. */
  minBudgetMs?: number
  /** A provider never gets more than this. */
  maxBudgetMs?: number
  /** How long an ordinary failure keeps a provider out of the chain. */
  failureCooldownMs?: number
  /** How long an exhausted balance keeps a provider out of the chain. */
  quotaCooldownMs?: number
  /** How long a provider that was too slow to answer is skipped. */
  slowCooldownMs?: number
}

interface ProviderState {
  /** How many successful answers were measured. */
  samples: number
  /** The average answer time, in milliseconds. */
  averageLatencyMs: number
  /** The provider is skipped until this moment. */
  skipUntil: number
  /** The provider was too slow to answer within its budget. */
  slow: boolean
}

const DEFAULTS = {
  defaultBudgetMs: 8_000,
  minBudgetMs: 5_000,
  maxBudgetMs: 20_000,
  failureCooldownMs: 60_000,
  quotaCooldownMs: 30 * 60_000,
  slowCooldownMs: 5 * 60_000,
} as const

/**
 * "Your balance is not enough" and friends.
 *
 * A service that ran out of credit will not recover in the next minute, so
 * it is benched for much longer than a connection hiccup.  Checking the
 * message instead of the status code matters because the same condition
 * arrives as HTTP 402 on one endpoint and as HTTP 200 with an error body
 * on another.
 */
export function isTtsQuotaMessage(message: string | undefined | null): boolean {
  if (!message)
    return false
  const low = message.toLowerCase()
  return low.includes('insufficient')
    || low.includes('quota')
    || low.includes('balance')
    || low.includes('余额')
    || low.includes('额度')
    || low.includes('用量上限')
    || low.includes('欠费')
    || low.includes('token plan')
}

export class TtsProviderScheduler {
  private readonly options: Required<TtsProviderSchedulerOptions>
  private readonly states = new Map<string, ProviderState>()

  constructor(options: TtsProviderSchedulerOptions = {}) {
    this.options = { ...DEFAULTS, ...options }
  }

  private state(providerId: string): ProviderState {
    let state = this.states.get(providerId)
    if (!state) {
      state = { samples: 0, averageLatencyMs: 0, skipUntil: 0, slow: false }
      this.states.set(providerId, state)
    }
    return state
  }

  /**
   * True while the provider is benched.
   *
   * A provider that is skipped is not even dialled, so a dead cloud key
   * costs nothing and a voice pack that is too slow for this machine is
   * not waited for.
   */
  isSkipped(providerId: string, now = Date.now()): boolean {
    const state = this.states.get(providerId)
    if (!state)
      return false
    if (state.skipUntil && state.skipUntil > now)
      return true
    if (state.skipUntil && state.skipUntil <= now)
      state.skipUntil = 0
    return false
  }

  /**
   * How long this provider may take before the next one is tried.
   *
   * The budget follows the measured speed: a provider that answered in one
   * second gets a few seconds of slack, a provider that took ten seconds
   * gets a bit more -- but never an unbounded amount, because the visitor
   * is waiting for an answer.
   */
  budgetFor(providerId: string): number {
    const state = this.states.get(providerId)
    if (!state)
      return this.options.defaultBudgetMs
    // A provider that already ran out of time once gets the smallest
    // budget: it is not broken, but on this machine it is not fast enough
    // to be worth waiting for.
    if (state.slow)
      return this.options.minBudgetMs
    if (state.samples === 0)
      return this.options.defaultBudgetMs
    const generous = Math.round(state.averageLatencyMs * 2.5)
    return Math.min(this.options.maxBudgetMs, Math.max(this.options.minBudgetMs, generous))
  }

  /** The provider answered in time. */
  recordSuccess(providerId: string, latencyMs: number): void {
    const state = this.state(providerId)
    const latency = Math.max(0, latencyMs)
    state.samples = state.samples + 1
    state.averageLatencyMs = state.samples === 1
      ? latency
      : Math.round(state.averageLatencyMs * 0.6 + latency * 0.4)
    // A provider that made it inside its budget is not slow any more.
    state.slow = false
    state.skipUntil = 0
  }

  /**
   * The provider did not answer in time.
   *
   * It is benched for a while so the next line does not pay the same wait
   * again, and its budget shrinks to what it actually managed -- so a
   * machine where the voice pack is hopeless stops trying it almost
   * entirely, while a machine where it is merely busy still gets its turn.
   */
  recordTimeout(providerId: string, now = Date.now()): void {
    const state = this.state(providerId)
    state.slow = true
    state.skipUntil = now + this.options.slowCooldownMs
  }

  /** The provider failed. */
  recordFailure(providerId: string, message?: string, now = Date.now()): void {
    const state = this.state(providerId)
    const cooldown = isTtsQuotaMessage(message)
      ? this.options.quotaCooldownMs
      : this.options.failureCooldownMs
    state.skipUntil = now + cooldown
  }

  /** Forget everything -- used by the settings screen and by the tests. */
  reset(): void {
    this.states.clear()
  }

  /** A snapshot for the diagnostics panel. */
  describe(providerId: string): {
    samples: number
    averageLatencyMs: number
    budgetMs: number
    skipped: boolean
    slow: boolean
  } {
    const state = this.states.get(providerId)
    return {
      samples: state?.samples ?? 0,
      averageLatencyMs: state?.averageLatencyMs ?? 0,
      budgetMs: this.budgetFor(providerId),
      skipped: this.isSkipped(providerId),
      slow: state?.slow ?? false,
    }
  }
}

/**
 * A signal that fires when either the caller aborts or the budget runs out.
 *
 * The speech pipeline already owns an abort signal for "the visitor left
 * the page"; the budget is a second, independent reason to stop waiting.
 */
export function createTtsBudgetSignal(
  outer: AbortSignal | undefined,
  budgetMs: number,
): { signal: AbortSignal, dispose: () => void } {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new Error('语音通道超时')), Math.max(500, budgetMs))
  const onOuterAbort = () => controller.abort(outer?.reason)

  if (outer) {
    if (outer.aborted)
      controller.abort(outer.reason)
    else
      outer.addEventListener('abort', onOuterAbort, { once: true })
  }

  return {
    signal: controller.signal,
    dispose: () => {
      clearTimeout(timer)
      outer?.removeEventListener('abort', onOuterAbort)
    },
  }
}
