export const CHAT_SEND_TIMEOUT_MS = 45_000

export class ChatSendTimeoutError extends Error {
  constructor() {
    super('Chat send timed out')
    this.name = 'ChatSendTimeoutError'
  }
}

/**
 * Put an upper bound around a UI send operation. The caller can abort the
 * orchestrator in the timeout callback, so a stalled provider cannot strand the
 * chat in a loading state forever.
 *
 * The bound is a *stall* detector, not a total-duration cap. A turn that keeps
 * making progress — streamed text, a running tool, a new message in the
 * conversation — resets the deadline, so a legitimately long turn (generating
 * four preview images, or a 3D model) is never cut off while it is still
 * working. Only a turn that stops producing anything for the whole window is
 * treated as stuck.
 *
 * `getProgressStamp` returns a value that changes whenever the turn makes
 * progress. When it is omitted the behaviour is that of a plain timeout.
 */
export async function withChatSendTimeout<T>(
  operation: Promise<T>,
  onTimeout: () => void,
  getProgressStamp?: () => unknown,
): Promise<T> {
  let lastStamp = getProgressStamp?.()
  let lastProgressAt = Date.now()
  let timeoutId: ReturnType<typeof setInterval> | undefined

  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setInterval(() => {
      const stamp = getProgressStamp?.()
      if (stamp !== undefined && !Object.is(stamp, lastStamp)) {
        lastStamp = stamp
        lastProgressAt = Date.now()
        return
      }

      if (Date.now() - lastProgressAt < CHAT_SEND_TIMEOUT_MS)
        return

      onTimeout()
      reject(new ChatSendTimeoutError())
    }, 2_000)
  })

  try {
    return await Promise.race([operation, timeout])
  }
  finally {
    if (timeoutId)
      clearInterval(timeoutId)
  }
}

export function notifyYXZChatRecovery() {
  if (typeof window === 'undefined')
    return

  window.dispatchEvent(new CustomEvent('yxz:chat-recovery'))
}
