export const CHAT_SEND_TIMEOUT_MS = 45_000

export class ChatSendTimeoutError extends Error {
  constructor() {
    super('Chat send timed out')
    this.name = 'ChatSendTimeoutError'
  }
}

/**
 * Put a hard upper bound around a UI send operation. The caller can abort the
 * orchestrator in the timeout callback, so a stalled provider cannot strand the
 * chat in a loading state forever.
 */
export async function withChatSendTimeout<T>(operation: Promise<T>, onTimeout: () => void): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined

  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      onTimeout()
      reject(new ChatSendTimeoutError())
    }, CHAT_SEND_TIMEOUT_MS)
  })

  try {
    return await Promise.race([operation, timeout])
  }
  finally {
    if (timeoutId)
      clearTimeout(timeoutId)
  }
}

export function notifyYXZChatRecovery() {
  if (typeof window === 'undefined')
    return

  window.dispatchEvent(new CustomEvent('yxz:chat-recovery'))
}
