import { storeToRefs } from 'pinia'

import { useChatSessionStore } from '@proj-airi/stage-ui/stores/chat/session-store'
import { useChatStreamStore } from '@proj-airi/stage-ui/stores/chat/stream-store'

/**
 * The stall detector needs to know whether the chat is still working.
 *
 * A turn can legitimately take minutes: four preview images plus a 3D model
 * produce no new text at all for a long time.  The watchdog only has to
 * avoid cutting those turns off.
 *
 * This used to live in the wide chat panel alone, so on a phone or a tablet
 * (and on any narrow window) the same turn was declared "stuck" after 90
 * seconds and aborted -- the tool call died half way, the backend kept
 * working, and the visitor was told the preview had failed while the
 * pictures were already on the server.  Both layouts use this helper now.
 */
export function useYXZChatTurnGuard() {
  const chatSession = useChatSessionStore()
  const chatStream = useChatStreamStore()
  const { messages } = storeToRefs(chatSession)

  /**
   * The newest 宜小智 creation card in the conversation.
   *
   * The card is rewritten in place while a build runs, and that card does
   * not have to be the last message: the visitor's confirmation ("就这个，
   * 开始生成 3D 模型吧") is appended after it.
   */
  function findLastCreationCard() {
    const list = messages.value
    for (let index = list.length - 1; index >= 0; index--) {
      const creation = (list[index] as { yxzCreation?: { status?: string, progressMsg?: string } } | undefined)?.yxzCreation
      if (creation)
        return creation
    }
    return undefined
  }

  /**
   * Everything that changes while a turn runs: the streamed text, the tool
   * calls and the messages that land in the conversation.  The watchdog
   * compares the stamp between two ticks, so any movement means "alive".
   */
  function chatProgressStamp() {
    const stream = chatStream.streamingMessage
    const sessionMessages = messages.value
    const last = sessionMessages.at(-1)
    const lastContent = last?.content
    const lastCreation = findLastCreationCard()

    return [
      stream?.content?.length ?? 0,
      stream?.slices?.length ?? 0,
      stream?.tool_results?.length ?? 0,
      sessionMessages.length,
      typeof lastContent === 'string' ? lastContent : '',
      lastCreation?.status ?? '',
      lastCreation?.progressMsg ?? '',
      // The raw provider activity: a reasoning model writes nothing while it
      // thinks, and the watchdog has to know that the turn is not dead.
      chatStream.lastActivityAt,
    ].join('|')
  }

  /**
   * True while the turn is busy with something that produces no chat text.
   */
  function chatTurnIsBusy() {
    const stream = chatStream.streamingMessage
    const toolCalls = stream?.slices?.filter(slice => slice.type === 'tool-call').length ?? 0
    const toolResults = stream?.tool_results?.length ?? 0
    if (toolCalls > toolResults)
      return true

    // A preview or a build that is running rewrites its card with progress
    // messages.
    const status = findLastCreationCard()?.status
    return status === 'model-building' || status === 'preview-building'
  }

  return { chatProgressStamp, chatTurnIsBusy, findLastCreationCard }
}
