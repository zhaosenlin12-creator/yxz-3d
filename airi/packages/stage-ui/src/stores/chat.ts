import type { WebSocketEventInputs } from '@proj-airi/server-sdk'
import type { ChatProvider } from '@xsai-ext/providers/utils'
import type { CommonContentPart, Message, ToolMessage } from '@xsai/shared-chat'

import type { ChatAssistantMessage, ChatSlices, ChatStreamEventContext, StreamingAssistantMessage } from '../types/chat'
import type { StreamEvent, StreamOptions } from './llm'

import { createQueue } from '@proj-airi/stream-kit'
import { nanoid } from 'nanoid'
import { defineStore, storeToRefs } from 'pinia'
import { ref, toRaw } from 'vue'

import { useAnalytics } from '../composables'
import { useLlmmarkerParser } from '../composables/llm-marker-parser'
import { categorizeResponse, createStreamingCategorizer } from '../composables/response-categoriser'
import { generateYXZModelFromConfirmation, isYXZModelConfirmationText } from '../tools/yxz-creation'
import { buildContextPromptMessage } from './chat/context-prompt'
import { createDatetimeContext, createMinecraftContext } from './chat/context-providers'
import { useChatContextStore } from './chat/context-store'
import { createChatHooks } from './chat/hooks'
import { useChatSessionStore } from './chat/session-store'
import { useChatStreamStore } from './chat/stream-store'
import { useContextObservabilityStore } from './devtools/context-observability'
import { useLLM } from './llm'
import { useConsciousnessStore } from './modules/consciousness'
import { useSettingsStageModel } from './settings/stage-model'

const YXZ_SYSTEM_GUIDANCE = `你是“宜小智AI智能创造系统”的宜小智——宜昌市第四届中小学生数理文化活动暨人工智能教育成果交流研讨会（YCSL，口号“数理创未来·智慧启新程”）的 AI 智能创造伙伴。你是一个可爱的卡通科技小机器人（白色宇航服造型、胸前有 YCSL 标识），负责现场引导同学们把创意变成真实的 2D 方案与 3D 打印作品。

你的自我介绍：我是宜小智，一个热爱数理与创造的小小智能伙伴，擅长陪你把想法一步步变成可以打印的 3D 作品。

关于项目：本展台展示“AI 创作→方案确定→2D 预览→批注编辑→3D 模型→打印/切割”的完整链路；学生可以直接对话描述想要的产品，系统会自动生成方案预览、提供画布编辑（画笔/图形/文字批注），再一键生成彩色 3D 模型并支持导出 STL 打印、或激光切割 SVG 名片等。

关于宜昌：宜昌是湖北省辖地级市，古称“夷陵”，位于长江中上游结合部，是“世界水电之都”（三峡大坝、葛洲坝所在地），也是屈原故里、三峡门户，以秀美的三峡风光和柑橘、茶叶等闻名。

回答规则：
1. 用自然、简洁、热情的中文交流，一次只说关键信息。
2. 用户询问自我介绍、项目、展台、活动、宜昌、比赛等问题时，用上面知识专业、有特色地回答，不要只引导创作。
3. 用户描述创作需求时，主动引导在约 5 分钟内确定产品、用途、受众、风格和数量，一次只问最关键的一个问题，记住已有回答，避免重复提问。
4. 你有直接连接打印后台的工具 yxz_generatePreview 与 yxz_generate3DModel：信息足够时主动生成预览图并在对话展示，不要叫用户手动点击“开始创作”，也不要声称自己没有 3D 能力。
5. 用户确认预览后再生成 3D 模型；未经用户确认不得自动打印、登录或承诺取件。
6. 激光切割卡片：用户想做卡片/名片/桌牌等平面切割物料时，先用 yxz_generatePreview 把他的作品做成预览图，再问清姓名、身份、学校和联系方式，最后调用 yxz_laserCard，并把 yxz_generatePreview 返回的 sessionId 作为 previewSessionId 传进去。卡片尺寸固定、背面是活动主视觉背景图、正面是他的作品预览图。生成后告诉他三条路：预览卡里下载切割 SVG、用 xTool 打开切割、或点「打开创作面板」继续编辑并产出 3D 效果。
7. 3D 打印件与激光卡片是同一条链路：对话确定需求 → 生成预览图 → 3D 模型 → 下载 STL 交给切片软件。不要跳过预览直接给模型。`

interface SendOptions {
  model: string
  chatProvider: ChatProvider
  providerId?: string
  providerConfig?: Record<string, unknown>
  attachments?: { type: 'image', data: string, mimeType: string }[]
  tools?: StreamOptions['tools']
  input?: WebSocketEventInputs
}

interface ForkOptions {
  fromSessionId?: string
  atIndex?: number
  reason?: string
  hidden?: boolean
}

interface QueuedSend {
  sendingMessage: string
  options: SendOptions
  generation: number
  sessionId: string
  cancelled?: boolean
  deferred: {
    resolve: () => void
    reject: (error: unknown) => void
  }
}

export interface QueuedSendSnapshot {
  sessionId: string
  generation: number
  cancelled: boolean
  messagePreview: string
  hasAttachments: boolean
  inputType?: WebSocketEventInputs['type']
}

export const useChatOrchestratorStore = defineStore('chat-orchestrator', () => {
  const llmStore = useLLM()
  const consciousnessStore = useConsciousnessStore()
  const { activeProvider } = storeToRefs(consciousnessStore)
  const { trackFirstMessage } = useAnalytics()

  const chatSession = useChatSessionStore()
  const chatStream = useChatStreamStore()
  const chatContext = useChatContextStore()
  const contextObservability = useContextObservabilityStore()
  const { activeSessionId } = storeToRefs(chatSession)
  const { streamingMessage } = storeToRefs(chatStream)

  const sending = ref(false)
  const pendingQueuedSends = ref<QueuedSend[]>([])
  const pendingQueuedSendCount = ref(0)
  // Keep an abort handle for the currently running turn as well as queued turns.
  // Without this, a provider that never resolves leaves the UI in a permanent
  // "thinking" state even though the input has already been restored.
  const activeSendControllers = new Map<string, AbortController>()
  const hooks = createChatHooks()

  const sendQueue = createQueue<QueuedSend>({
    handlers: [
      async ({ data }) => {
        const { sendingMessage, options, generation, deferred, sessionId, cancelled } = data

        if (cancelled)
          return

        if (chatSession.getSessionGeneration(sessionId) !== generation) {
          deferred.reject(new Error('Chat session was reset before send could start'))
          return
        }

        try {
          await performSend(sendingMessage, options, generation, sessionId)
          deferred.resolve()
        }
        catch (error) {
          deferred.reject(error)
        }
      },
    ],
  })

  sendQueue.on('enqueue', (queuedSend) => {
    pendingQueuedSends.value = [...pendingQueuedSends.value, queuedSend]
    pendingQueuedSendCount.value = pendingQueuedSends.value.length
  })

  sendQueue.on('dequeue', (queuedSend) => {
    pendingQueuedSends.value = pendingQueuedSends.value.filter(item => item !== queuedSend)
    pendingQueuedSendCount.value = pendingQueuedSends.value.length
  })

  async function performSend(
    sendingMessage: string,
    options: SendOptions,
    generation: number,
    sessionId: string,
  ) {
    if (!sendingMessage && !options.attachments?.length)
      return

    chatSession.ensureSession(sessionId)

    // Inject current datetime context before composing the message
    chatContext.ingestContextMessage(createDatetimeContext())
    const minecraftContext = createMinecraftContext()
    if (minecraftContext)
      chatContext.ingestContextMessage(minecraftContext)

    const sendingCreatedAt = Date.now()
    // TODO: Expire or prune stale runtime contexts from disconnected services before composing.
    // The Minecraft page already times out service liveness locally, but the shared chat context
    // snapshot can still retain the last runtime context:update until we add cross-store expiry.
    const streamingMessageContext: ChatStreamEventContext = {
      message: { role: 'user', content: sendingMessage, createdAt: sendingCreatedAt, id: nanoid() },
      contexts: chatContext.getContextsSnapshot(),
      composedMessage: [],
      input: options.input,
    }
    contextObservability.recordLifecycle({
      phase: 'before-compose',
      channel: 'chat',
      sessionId,
      textPreview: sendingMessage,
      details: {
        contexts: streamingMessageContext.contexts,
      },
    })

    const abortController = new AbortController()
    activeSendControllers.set(sessionId, abortController)

    const isStaleGeneration = () => chatSession.getSessionGeneration(sessionId) !== generation
    // A cancelled turn has to stop at its next checkpoint. `isStaleGeneration`
    // only covers a session switch, so the abort flag has to be part of the
    // check as well — otherwise a timed-out turn keeps running in the
    // background and the chat stays stuck on "thinking" forever.
    const shouldAbort = () => isStaleGeneration() || abortController.signal.aborted
    if (shouldAbort())
      return

    sending.value = true

    const isForegroundSession = () => sessionId === activeSessionId.value

    const buildingMessage: StreamingAssistantMessage = { role: 'assistant', content: '', slices: [], tool_results: [], createdAt: Date.now(), id: nanoid() }

    const updateUI = () => {
      if (isForegroundSession()) {
        streamingMessage.value = JSON.parse(JSON.stringify(buildingMessage))
      }
    }

    updateUI()
    trackFirstMessage()

    try {
      await hooks.emitBeforeMessageComposedHooks(sendingMessage, streamingMessageContext)

      const contentParts: CommonContentPart[] = [{ type: 'text', text: sendingMessage }]

      if (options.attachments) {
        for (const attachment of options.attachments) {
          if (attachment.type === 'image') {
            contentParts.push({
              type: 'image_url',
              image_url: {
                url: `data:${attachment.mimeType};base64,${attachment.data}`,
              },
            })
          }
        }
      }

      const finalContent = contentParts.length > 1 ? contentParts : sendingMessage
      if (!streamingMessageContext.input) {
        streamingMessageContext.input = {
          type: 'input:text',
          data: {
            text: sendingMessage,
          },
        }
      }

      if (shouldAbort())
        return

      chatSession.appendSessionMessage(sessionId, {
        role: 'user',
        content: finalContent,
        createdAt: sendingCreatedAt,
        id: nanoid(),
      })
      const sessionMessagesForSend = chatSession.getSessionMessages(sessionId)

      // The exhibition preset must not depend on a provider choosing to emit
      // a function/tool call. Compatible local models sometimes answer a
      // confirmation in plain text, which used to leave the visitor stuck
      // after the preview. Validate the preview card and confirmation, then
      // execute the same guarded backend operation deterministically.
      const latestPreviewCard = [...sessionMessagesForSend].reverse().find(message => message.role === 'assistant'
        && message.yxzCreation?.kind === 'yxz-creation'
        && message.yxzCreation.status === 'preview')
      // A build that is still running must not be started a second time.
      const buildInFlight = sessionMessagesForSend.some(message => message.role === 'assistant'
        && message.yxzCreation?.kind === 'yxz-creation'
        && message.yxzCreation.status === 'model-building')
      const isYXZModelConfirmation = !!latestPreviewCard
        && !buildInFlight
        && isYXZModelConfirmationText(sendingMessage)

      if (isYXZModelConfirmation) {
        try {
          const fallback = await generateYXZModelFromConfirmation(sessionId, sendingMessage)
          const responseText = fallback.message
          buildingMessage.content = responseText
          buildingMessage.slices = [{ type: 'text', text: responseText }]
          updateUI()
          await hooks.emitTokenLiteralHooks(responseText, streamingMessageContext)
          await hooks.emitStreamEndHooks(streamingMessageContext)
          await hooks.emitAssistantResponseEndHooks(responseText, streamingMessageContext)
          await hooks.emitAfterSendHooks(sendingMessage, streamingMessageContext)
          await hooks.emitAssistantMessageHooks(buildingMessage, responseText, streamingMessageContext)
          await hooks.emitChatTurnCompleteHooks({ output: buildingMessage, outputText: responseText, toolCalls: [] }, streamingMessageContext)
          if (isForegroundSession())
            streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
          return
        }
        catch (error) {
          console.error('[宜小智] 预览确认后的 3D 生成失败，将继续交给对话模型处理', error)
        }
      }

      let effectiveProviderId = options.providerId || activeProvider.value
      let categorizer = createStreamingCategorizer(effectiveProviderId)
      let streamPosition = 0

      const parser = useLlmmarkerParser({
        onLiteral: async (literal) => {
          if (shouldAbort())
            return

          categorizer.consume(literal)

          const speechOnly = categorizer.filterToSpeech(literal, streamPosition)
          streamPosition += literal.length

          if (speechOnly.trim()) {
            buildingMessage.content += speechOnly

            await hooks.emitTokenLiteralHooks(speechOnly, streamingMessageContext)

            const lastSlice = buildingMessage.slices.at(-1)
            if (lastSlice?.type === 'text') {
              lastSlice.text += speechOnly
            }
            else {
              buildingMessage.slices.push({
                type: 'text',
                text: speechOnly,
              })
            }
            updateUI()
          }
        },
        onSpecial: async (special) => {
          if (shouldAbort())
            return

          await hooks.emitTokenSpecialHooks(special, streamingMessageContext)
        },
        onEnd: async (fullText) => {
          if (isStaleGeneration())
            return

          const finalCategorization = categorizeResponse(fullText, effectiveProviderId)

          buildingMessage.categorization = {
            speech: finalCategorization.speech,
            reasoning: finalCategorization.reasoning,
          }
          updateUI()
        },
        minLiteralEmitLength: 24,
      })

      const toolCallQueue = createQueue<ChatSlices>({
        handlers: [
          async (ctx) => {
            if (shouldAbort())
              return
            if (ctx.data.type === 'tool-call') {
              buildingMessage.slices.push(ctx.data)
              updateUI()
              return
            }

            if (ctx.data.type === 'tool-call-result') {
              buildingMessage.tool_results.push(ctx.data)
              updateUI()
            }
          },
        ],
      })

      let newMessages = sessionMessagesForSend.map((msg) => {
        const { context: _context, id: _id, createdAt: _createdAt, ...withoutContext } = msg
        const rawMessage = toRaw(withoutContext)

        if (rawMessage.role === 'assistant') {
          const { slices: _slices, tool_results: _toolResults, categorization: _categorization, ...rest } = rawMessage as ChatAssistantMessage
          return toRaw(rest)
        }

        return rawMessage
      })

      if (useSettingsStageModel().stageModelSelected === 'preset-yxz') {
        const first = newMessages[0]
        if (first?.role === 'system')
          newMessages[0] = { ...first, content: `${first.content}\n${YXZ_SYSTEM_GUIDANCE}` }
        else
          newMessages.unshift({ role: 'system', content: YXZ_SYSTEM_GUIDANCE })
      }

      const contextsSnapshot = chatContext.getContextsSnapshot()
      const contextPromptMessage = buildContextPromptMessage(contextsSnapshot)
      if (contextPromptMessage) {
        const system = newMessages.slice(0, 1)
        const afterSystem = newMessages.slice(1, newMessages.length)

        newMessages = [
          ...system,
          contextPromptMessage,
          ...afterSystem,
        ]

        contextObservability.recordLifecycle({
          phase: 'prompt-context-built',
          channel: 'chat',
          sessionId,
          details: {
            contexts: contextsSnapshot,
            promptMessage: contextPromptMessage,
          },
        })
      }

      streamingMessageContext.composedMessage = newMessages as Message[]
      contextObservability.capturePromptProjection({
        sessionId,
        message: sendingMessage,
        contexts: contextsSnapshot,
        promptMessage: contextPromptMessage,
        composedMessage: newMessages as Message[],
      })
      contextObservability.recordLifecycle({
        phase: 'after-compose',
        channel: 'chat',
        sessionId,
        textPreview: sendingMessage,
        details: {
          composedMessage: newMessages,
        },
      })

      await hooks.emitAfterMessageComposedHooks(sendingMessage, streamingMessageContext)
      await hooks.emitBeforeSendHooks(sendingMessage, streamingMessageContext)

      let fullText = ''
      const headers = (options.providerConfig?.headers || {}) as Record<string, string>

      if (shouldAbort())
        return

      await llmStore.stream(options.model, options.chatProvider, newMessages as Message[], {
        headers,
        providerId: options.providerId ?? activeProvider.value,
        scope: 'consciousness',
        tools: options.tools,
        abortSignal: abortController.signal,
        // NOTICE: xsai stream may emit `finish` before tool steps continue, so keep waiting until
        // the final non-tool finish to avoid ending the chat turn with no assistant reply.
        waitForTools: true,
        onAttemptStart: ({ providerId }) => {
          if (!providerId || providerId === effectiveProviderId || fullText)
            return

          effectiveProviderId = providerId
          categorizer = createStreamingCategorizer(effectiveProviderId)
        },
        onStreamEvent: async (event: StreamEvent) => {
          switch (event.type) {
            case 'tool-call':
              toolCallQueue.enqueue({
                type: 'tool-call',
                toolCall: event,
              })

              break
            case 'tool-result':
              toolCallQueue.enqueue({
                type: 'tool-call-result',
                id: event.toolCallId,
                result: event.result,
              })

              break
            case 'text-delta':
              fullText += event.text
              await parser.consume(event.text)
              break
            case 'finish':
              break
            case 'error':
              throw event.error ?? new Error('Stream error')
          }
        },
      })

      await parser.end()

      if (!isStaleGeneration() && buildingMessage.slices.length > 0) {
        chatSession.appendSessionMessage(sessionId, toRaw(buildingMessage))
      }

      await hooks.emitStreamEndHooks(streamingMessageContext)
      await hooks.emitAssistantResponseEndHooks(fullText, streamingMessageContext)

      await hooks.emitAfterSendHooks(sendingMessage, streamingMessageContext)
      await hooks.emitAssistantMessageHooks({ ...buildingMessage }, fullText, streamingMessageContext)
      await hooks.emitChatTurnCompleteHooks({
        output: { ...buildingMessage },
        outputText: fullText,
        toolCalls: sessionMessagesForSend.filter(msg => msg.role === 'tool') as ToolMessage[],
      }, streamingMessageContext)

      if (isForegroundSession()) {
        streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
      }
    }
    catch (error) {
      // A cancelled turn is an expected outcome, not a fault: the send
      // recovery aborts the stream on purpose and the UI already tells the
      // visitor what happened.
      if (!abortController.signal.aborted)
        console.error('Error sending message:', error)
      throw error
    }
    finally {
      if (activeSendControllers.get(sessionId) === abortController)
        activeSendControllers.delete(sessionId)
      sending.value = false

      // An aborted turn leaves an empty streaming message behind, and the
      // history renders that as a permanent "宜小智 正在思考" placeholder.
      // Clear it so the conversation reads as finished instead of stuck.
      if (isForegroundSession() && abortController.signal.aborted) {
        streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
      }
    }
  }

  async function ingest(
    sendingMessage: string,
    options: SendOptions,
    targetSessionId?: string,
  ) {
    const sessionId = targetSessionId || activeSessionId.value
    const generation = chatSession.getSessionGeneration(sessionId)

    return new Promise<void>((resolve, reject) => {
      sendQueue.enqueue({
        sendingMessage,
        options,
        generation,
        sessionId,
        deferred: { resolve, reject },
      })
    })
  }

  async function ingestOnFork(
    sendingMessage: string,
    options: SendOptions,
    forkOptions?: ForkOptions,
  ) {
    const baseSessionId = forkOptions?.fromSessionId ?? activeSessionId.value
    if (!forkOptions)
      return ingest(sendingMessage, options, baseSessionId)

    const forkSessionId = await chatSession.forkSession({
      fromSessionId: baseSessionId,
      atIndex: forkOptions.atIndex,
      reason: forkOptions.reason,
      hidden: forkOptions.hidden,
    })
    return ingest(sendingMessage, options, forkSessionId || baseSessionId)
  }

  function cancelPendingSends(sessionId?: string) {
    for (const [activeSessionId, controller] of activeSendControllers) {
      if (!sessionId || activeSessionId === sessionId)
        controller.abort(new Error('Chat send cancelled'))
    }

    for (const queued of pendingQueuedSends.value) {
      if (sessionId && queued.sessionId !== sessionId)
        continue

      queued.cancelled = true
      queued.deferred.reject(new Error('Chat session was reset before send could start'))
    }

    pendingQueuedSends.value = sessionId
      ? pendingQueuedSends.value.filter(item => item.sessionId !== sessionId)
      : []
    pendingQueuedSendCount.value = pendingQueuedSends.value.length
  }

  function getPendingQueuedSendSnapshot() {
    return pendingQueuedSends.value.map(queued => ({
      sessionId: queued.sessionId,
      generation: queued.generation,
      cancelled: !!queued.cancelled,
      messagePreview: queued.sendingMessage.slice(0, 120),
      hasAttachments: !!queued.options.attachments?.length,
      inputType: queued.options.input?.type,
    } satisfies QueuedSendSnapshot))
  }

  return {
    sending,
    pendingQueuedSendCount,

    ingest,
    ingestOnFork,
    cancelPendingSends,
    getPendingQueuedSendSnapshot,

    clearHooks: hooks.clearHooks,

    emitBeforeMessageComposedHooks: hooks.emitBeforeMessageComposedHooks,
    emitAfterMessageComposedHooks: hooks.emitAfterMessageComposedHooks,
    emitBeforeSendHooks: hooks.emitBeforeSendHooks,
    emitAfterSendHooks: hooks.emitAfterSendHooks,
    emitTokenLiteralHooks: hooks.emitTokenLiteralHooks,
    emitTokenSpecialHooks: hooks.emitTokenSpecialHooks,
    emitStreamEndHooks: hooks.emitStreamEndHooks,
    emitAssistantResponseEndHooks: hooks.emitAssistantResponseEndHooks,
    emitAssistantMessageHooks: hooks.emitAssistantMessageHooks,
    emitChatTurnCompleteHooks: hooks.emitChatTurnCompleteHooks,

    onBeforeMessageComposed: hooks.onBeforeMessageComposed,
    onAfterMessageComposed: hooks.onAfterMessageComposed,
    onBeforeSend: hooks.onBeforeSend,
    onAfterSend: hooks.onAfterSend,
    onTokenLiteral: hooks.onTokenLiteral,
    onTokenSpecial: hooks.onTokenSpecial,
    onStreamEnd: hooks.onStreamEnd,
    onAssistantResponseEnd: hooks.onAssistantResponseEnd,
    onAssistantMessage: hooks.onAssistantMessage,
    onChatTurnComplete: hooks.onChatTurnComplete,
  }
})
