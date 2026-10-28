/**
 * How long a turn may stay completely silent before it counts as stuck.
 *
 * The number has to cover the slowest thing a turn legitimately does:
 * a reasoning model that thinks before it writes its first word, and a
 * tool call that renders four preview images (about a minute on the cloud
 * image services).  The old 45s window cut both of those off, which is why
 * the visitor saw "连接等待时间较长 / 请切换一个可用模型" in the middle of
 * a perfectly healthy run.
 */
export const CHAT_SEND_TIMEOUT_MS = 90_000

/**
 * Absolute ceiling for one chat turn.
 *
 * The stall detector is a silence detector, so a turn that keeps making
 * noise would never time out on its own.  This cap is the safety net that
 * stops a runaway turn from blocking the chat forever.
 */
export const CHAT_SEND_MAX_TURN_MS = 20 * 60_000

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
  options?: {
    /**
     * True while the turn is legitimately working on something that does
     * not show up as visible text -- a running tool call, a rendering
     * pipeline, a model that is still thinking.  A busy turn is never
     * treated as stalled.
     */
    isTurnActive?: () => boolean
    /** Hard ceiling for the whole turn, in milliseconds. */
    maxTurnMs?: number
  },
): Promise<T> {
  let lastStamp = getProgressStamp?.()
  let lastProgressAt = Date.now()
  const startedAt = lastProgressAt
  const maxTurnMs = options?.maxTurnMs ?? CHAT_SEND_MAX_TURN_MS
  let timeoutId: ReturnType<typeof setInterval> | undefined

  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setInterval(() => {
      // The absolute ceiling comes first: it is the safety net that stops a
      // runaway turn, no matter how busy it claims to be.
      if (Date.now() - startedAt >= maxTurnMs) {
        onTimeout()
        reject(new ChatSendTimeoutError())
        return
      }

      const stamp = getProgressStamp?.()
      if (stamp !== undefined && !Object.is(stamp, lastStamp)) {
        lastStamp = stamp
        lastProgressAt = Date.now()
        return
      }

      // A turn that is busy is not a stuck turn.  Long tool calls (four
      // preview images, a 3D build) produce no chat text for minutes at a
      // time, and aborting them is what used to break the guided flow.
      if (options?.isTurnActive?.()) {
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
