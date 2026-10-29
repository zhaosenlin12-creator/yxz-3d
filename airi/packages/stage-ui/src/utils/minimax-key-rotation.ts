/**
 * MiniMax never answers a rejected key with an HTTP error: an exhausted
 * Token Plan or a wrong credential comes back as HTTP 200 with a body that
 * carries `base_resp.status_code`. The frontend therefore has to read the
 * payload instead of trusting the status code.
 *
 * `splitApiKeys` lets one provider config hold several platform keys and
 * `createMinimaxKeyRotatingFetch` retries the request with the next key as
 * soon as the current one is rejected, so a single exhausted key never takes
 * the whole app down.
 */

const KEY_SEPARATOR = /[\s,;]+/

/**
 * How long a key stays benched after it refused to work.
 *
 * An exhausted Token Plan does not recover on its own, so every request
 * that walks the list again would pay for one more doomed round trip --
 * and every one of them leaves a red 429 in the browser console, which
 * looks like a broken app to the visitor.
 */
export const MINIMAX_DEAD_KEY_COOLDOWN_MS = 60 * 60 * 1000

/** key -> the moment it may be tried again */
const deadKeys = new Map<string, number>()

/** Remember that this key cannot serve requests for now. */
export function markMinimaxKeyDead(key: string, cooldownMs = MINIMAX_DEAD_KEY_COOLDOWN_MS): void {
  if (!key)
    return
  deadKeys.set(key, Date.now() + Math.max(1000, cooldownMs))
}

/** True while the key is benched. */
export function isMinimaxKeyDead(key: string, now = Date.now()): boolean {
  const until = deadKeys.get(key)
  if (until === undefined)
    return false
  if (until <= now) {
    deadKeys.delete(key)
    return false
  }
  return true
}

/** Forget every benched key -- used when the plan was topped up. */
export function resetMinimaxDeadKeys(): void {
  deadKeys.clear()
}

/** How many keys are currently benched (for diagnostics). */
export function countMinimaxDeadKeys(): number {
  for (const [key, until] of [...deadKeys]) {
    if (until <= Date.now())
      deadKeys.delete(key)
  }
  return deadKeys.size
}

/**
 * A key is "spent" when MiniMax says the Token Plan or the balance ran
 * out.  That is different from a wrong credential: the key was fine
 * yesterday, so it deserves a bench rather than a permanent blacklist.
 */
function isMinimaxQuotaMessage(message: string): boolean {
  const low = message.toLowerCase()
  return low.includes('token plan')
    || low.includes('rate_limit')
    || low.includes('rate limit')
    || low.includes('quota')
    || low.includes('insufficient')
    || low.includes('用量上限')
    || low.includes('额度')
    || low.includes('余额')
    || low.includes('欠费')
}

/** Split a provider API key field into individual, non-empty keys. */
export function splitApiKeys(raw: unknown): string[] {
  if (typeof raw !== 'string')
    return []

  return raw
    .split(KEY_SEPARATOR)
    .map(key => key.trim())
    .filter(Boolean)
}

/** Read MiniMax's `base_resp` error message, if the payload carries one. */
export function readMinimaxError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object')
    return undefined

  const baseResp = (payload as { base_resp?: { status_code?: number, status_msg?: string } }).base_resp
  if (!baseResp)
    return undefined

  const code = baseResp.status_code
  if (code === undefined || code === null || code === 0)
    return undefined

  return baseResp.status_msg || `MiniMax error ${code}`
}

/**
 * Parse the payload of a MiniMax response, both the plain JSON shape and the
 * single `data:` line of an SSE stream. Returns undefined when the text is
 * not (yet) valid JSON, which keeps a chunk boundary from being mistaken for
 * a provider error.
 */
function parseMinimaxPayload(text: string): unknown {
  const trimmed = text.trim()
  if (trimmed.startsWith('{')) {
    try {
      return JSON.parse(trimmed)
    }
    catch {
      // fall through to the SSE shape
    }
  }

  for (const line of text.split('\n')) {
    const candidate = line.trim()
    if (!candidate.startsWith('data:'))
      continue

    const payload = candidate.slice(5).trim()
    if (!payload || payload === '[DONE]')
      continue

    try {
      return JSON.parse(payload)
    }
    catch {
      return undefined
    }
  }

  return undefined
}

/**
 * Build a `fetch` that walks the configured MiniMax keys in order.
 *
 * The first chunk of the response is inspected before it is handed over: a
 * rejected key is answered with HTTP 200 plus an error payload, so the
 * status code alone cannot tell a working key from a dead one.
 */
export function createMinimaxKeyRotatingFetch(keys: string[]): typeof globalThis.fetch {
  const all = keys.filter(Boolean)

  return async (input: RequestInfo | URL, init?: RequestInit) => {
    if (all.length === 0)
      return globalThis.fetch(input, init)

    // A benched key is skipped; if that leaves nothing, the plan was
    // probably topped up in the meantime, so forget the bench and retry.
    let candidates = all.filter(key => !isMinimaxKeyDead(key))
    if (candidates.length === 0) {
      resetMinimaxDeadKeys()
      candidates = all
    }

    let lastError: Error | undefined

    for (const key of candidates) {
      const requestHeaders = new Headers(init?.headers ?? undefined)
      requestHeaders.set('authorization', `Bearer ${key}`)

      const response = await globalThis.fetch(input, { ...init, headers: requestHeaders })

      if (!response.ok) {
        // 401 / 403 / 429 mean this key cannot serve the request.
        if (response.status === 401 || response.status === 403 || response.status === 429) {
          markMinimaxKeyDead(key)
          lastError = new Error(`MiniMax rejected the key (HTTP ${response.status})`)
          continue
        }
        return response
      }

      const body = response.body
      if (!body)
        return response

      const reader = body.getReader()
      const first = await reader.read()
      const peeked = first.done ? '' : new TextDecoder().decode(first.value)
      const message = readMinimaxError(parseMinimaxPayload(peeked))

      if (message && !first.done) {
        // The key is rejected: drop this response and try the next key.
        await reader.cancel().catch(() => {})
        if (isMinimaxQuotaMessage(message))
          markMinimaxKeyDead(key)
        lastError = new Error(message)
        continue
      }

      const responseHeaders = new Headers(response.headers)
      responseHeaders.delete('content-length')
      responseHeaders.delete('content-encoding')

      const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
          if (!first.done)
            controller.enqueue(first.value)

          try {
            for (;;) {
              const next = await reader.read()
              if (next.done) {
                controller.close()
                break
              }
              controller.enqueue(next.value)
            }
          }
          catch (error) {
            controller.error(error)
          }
        },
        cancel(reason) {
          void reader.cancel(reason)
        },
      })

      return new Response(stream, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      })
    }

    throw lastError ?? new Error('MiniMax request failed: no usable API key')
  }
}
