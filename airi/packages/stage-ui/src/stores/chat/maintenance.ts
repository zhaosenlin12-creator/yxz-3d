import { defineStore } from 'pinia'

import { useYXZRequirementMemory } from '../../composables/use-yxz-requirement-memory'
import { useChatOrchestratorStore } from '../chat'
import { useChatContextStore } from './context-store'
import { useChatSessionStore } from './session-store'
import { useChatStreamStore } from './stream-store'

export const useChatMaintenanceStore = defineStore('chat-maintenance', () => {
  const chatSession = useChatSessionStore()
  const chatStream = useChatStreamStore()
  const chatContext = useChatContextStore()
  const chatOrchestrator = useChatOrchestratorStore()

  function cleanupMessages(sessionId = chatSession.activeSessionId) {
    chatSession.cleanupMessages(sessionId)
    chatContext.resetContexts()
    chatOrchestrator.cancelPendingSends(sessionId)
    chatStream.resetStream()
    // Cleaning the conversation means "start over".  The requirement
    // memory has to go with it, otherwise the picture that was uploaded
    // in the old conversation keeps being used as the shape reference of
    // the next one.
    useYXZRequirementMemory().clear(sessionId)
  }

  return {
    cleanupMessages,
  }
})
