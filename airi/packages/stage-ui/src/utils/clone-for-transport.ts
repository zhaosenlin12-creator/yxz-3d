/**
 * Clone values that cross BroadcastChannel/extension boundaries.
 *
 * Tool-call payloads can contain functions, symbols, DOM objects, or circular
 * references. Native structuredClone intentionally rejects those values; the
 * transport still needs a useful, serializable snapshot instead of breaking
 * the chat turn.
 */
export function cloneForTransport<T>(value: T): T {
  try {
    return structuredClone(value)
  }
  catch {
    const seen = new WeakSet<object>()

    const sanitize = (input: unknown): unknown => {
      if (input === null || typeof input === 'string' || typeof input === 'number' || typeof input === 'boolean')
        return input
      if (typeof input === 'bigint')
        return input.toString()
      if (typeof input === 'undefined' || typeof input === 'function' || typeof input === 'symbol')
        return undefined
      if (input instanceof Date)
        return input.toISOString()
      if (typeof input !== 'object')
        return String(input)
      if (seen.has(input))
        return '[Circular]'

      seen.add(input)
      if (Array.isArray(input))
        return input.map(item => sanitize(item)).filter(item => typeof item !== 'undefined')

      const output: Record<string, unknown> = {}
      for (const [key, item] of Object.entries(input)) {
        const sanitized = sanitize(item)
        if (typeof sanitized !== 'undefined')
          output[key] = sanitized
      }
      return output
    }

    return sanitize(value) as T
  }
}
