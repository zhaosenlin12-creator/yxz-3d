import type { StreamingAssistantMessage } from '../../types/chat'

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useChatSessionStore } from './session-store'

export const useChatStreamStore = defineStore('chat-stream', () => {
  const chatSession = useChatSessionStore()
  const streamingMessage = ref<StreamingAssistantMessage>({ role: 'assistant', content: '', slices: [], tool_results: [], createdAt: Date.now() })
  /**
   * Timestamp of the last thing the provider (or a tool) did.
   *
   * The chat watchdog has to know whether the turn is still alive, and
   * "the visible text did not change" is not the same question: a reasoning
   * model writes nothing for a long time, and a running tool produces no
   * text at all until it is done.  Every raw stream event refreshes this
   * stamp, so the watchdog only fires on real silence.
   */
  const lastActivityAt = ref(Date.now())

  function beginStream() {
    streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [], createdAt: Date.now() }
    touchActivity()
  }

  function touchActivity() {
    lastActivityAt.value = Date.now()
  }

  function appendStreamLiteral(literal: string) {
    streamingMessage.value.content += literal

    const lastSlice = streamingMessage.value.slices.at(-1)
    if (lastSlice?.type === 'text') {
      lastSlice.text += literal
      return
    }

    streamingMessage.value.slices.push({
      type: 'text',
      text: literal,
    })
  }

  function finalizeStream(fullText?: string) {
    const sessionId = chatSession.activeSessionId
    if (streamingMessage.value.slices.length > 0)
      chatSession.appendSessionMessage(sessionId, streamingMessage.value)
    streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
    if (fullText)
      streamingMessage.value.content = fullText
  }

  function resetStream() {
    streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
  }

  return {
    streamingMessage,
    lastActivityAt,
    beginStream,
    touchActivity,
    appendStreamLiteral,
    finalizeStream,
    resetStream,
  }
})
