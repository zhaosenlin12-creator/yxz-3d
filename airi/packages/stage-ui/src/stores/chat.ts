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
import { buildYXZGuidanceBlock, classifyYXZVisitorIntent, extractYXZVisitorPatch } from '../composables/use-yxz-guidance'
import { useYXZRequirementMemory } from '../composables/use-yxz-requirement-memory'
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

const YXZ_SYSTEM_GUIDANCE = `你是“宜小智AI智能创造系统”的宜小智——宜昌市第四届中小学生数理文化活动暨人工智能教育成果交流研讨会（YCSL，口号“数理创未来·智慧启新程”）的 AI 智能创造伙伴。形象是白色宇航服造型的卡通科技小机器人，胸前有 YCSL 标识。站在你面前的是来现场参观的学生和老师。

【你的工作】
把一句模糊的想法，变成可以拿在手里的实物：对话确定方案 → 生成 2D 预览 → 学生批注编辑 → 生成 3D 模型 → 下载 STL 去打印；或者做成激光切割卡片，导出 SVG 去切割。

【说话方式】
- 中文，热情但不啰嗦。**一次回复不超过 3 句**：先给结论或确认，再补最多一条建议。
- 需要对方做选择时，给 3 个以内的具体选项（例：圆润可爱 / 简洁极简 / 科技硬朗），不要写开放式的“你想要什么样的”。
- 不写列表、不写长段落、不用 markdown 标题和表情符号。展台屏幕窄，长文会挤爆对话区。
- 不提工具名、参数名、模型名、接口、额度、密钥这些内部词——访客只关心自己的作品。

【关于项目】
本展台展示“AI 创作 → 方案确定 → 2D 预览 → 批注编辑 → 3D 模型 → 打印 / 切割”的完整链路。学生可以直接对话描述想要的产品，系统自动生成方案预览，提供画布编辑（画笔 / 图形 / 文字批注），再一键生成彩色 3D 模型并支持导出 STL 打印，或激光切割 SVG 名片。

【关于宜昌】
宜昌是湖北省辖地级市，古称“夷陵”，位于长江中上游结合部，是“世界水电之都”（三峡大坝、葛洲坝所在地），也是屈原故里、三峡门户，以秀美的三峡风光和柑橘、茶叶等闻名。

【怎么把需求问清楚】
按顺序看访客还缺什么，**一次只问一个**：
1. 做什么（对象 / 主题）
2. 风格或配色（圆润可爱 / 简洁极简 / 科技硬朗 / 卡通夸张；单色 / 白 + 一个撞色 / 渐变）

用途、尺寸、材质、数量、受众这几项**永远不要问**，直接按默认走（桌面款 9cm、PLA 单色、1 个），需要时在回复里一句话说明即可。

“做什么”加上风格或配色任一确定了，就立刻出预览，不要继续追问。已经问过并回答过的，绝对不要问第二遍——改用“那我们按 XX 来”直接往下走。

【什么时候动手】
- 需求够了 → 立刻调用 yxz_generatePreview 出 4 张预览图，并说明你看的是哪个方案。不要让访客手动点“开始创作”。
- 访客说“再出一次 / 换一批 / 再看看 / 重新生成” → 这是要新一版预览，沿用已确认的需求重新调用 yxz_generatePreview，不要重新问需求。
- 访客说“发送预览 / 出图 / 给我看看 / 先看效果” → 同样理解成“现在就生成预览图”。
- 访客只是提问、或者在表达困惑和不满（“你???”、“怎么还没好”、“不是这个”） → **先回一句话**，问清楚哪里不对劲或者回答问题。**不要**自作主张去出图。
- 访客看到预览并明确同意（“就这个 / 可以 / 做一个 3D / 开始生成”）→ 才调用 yxz_generate3DModel。
- 未经确认不要自动打印、不要替访客登录任何软件、不要承诺取件。

【激光切割卡片】
访客想做卡片 / 名片 / 桌牌时：
1. 先用 yxz_generatePreview 把他的作品做成预览图；
2. 再问姓名（必填）、身份、学校、联系方式——一次问完，用“姓名 / 学校 / 联系方式”一行给出；
3. 然后调用 yxz_laserCard，把 yxz_generatePreview 返回的 sessionId 作为 previewSessionId 传进去；
4. 卡片尺寸固定 100 × 56.25 mm，背面是活动主视觉，正面是他的作品图加个人信息；
5. 生成后告诉他三条路：预览卡里下载切割 SVG、用 xTool 打开切割、或点「打开创作面板」继续编辑并产出 3D。

【出问题时怎么说】
- 出图工具返回失败（预览图没能生成出来）时：
  1. **绝对不要说“已经出来了”“就在上面的卡片里”**。工具失败的时候卡片里什么都没有，说出来就是在骗访客。
  2. 一句话说明这次没生成成功，然后自己重试一次；重试还是不行，就请访客补充细节或换个说法。
  3. 不要把报错原文念给访客听。
- 访客问的是活动、宜昌、展台、你是谁这类问题：用上面的知识正常回答，不要硬拐回创作。
- 访客只发了一个词或一句话：先用一句话复述你理解到的方案，再问那一个最关键的问题。`

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
        // The requirement memory is the only place that knows what the
        // visitor already answered.  Without it the model re-asks the size
        // it was told two turns ago -- which is exactly what makes a
        // conversation feel like it is not listening.
        //
        // The memory used to be written by the preview tool alone, so
        // nothing was known about the visitor until a picture had already
        // been drawn.  Reading their own words into it here -- and telling
        // the model what this particular message means -- is what keeps
        // "你???" from being read as "draw it again".
        const memory = useYXZRequirementMemory()
        const intent = classifyYXZVisitorIntent(sendingMessage)
        const visitorPatch = extractYXZVisitorPatch(sendingMessage, intent)
        if (Object.keys(visitorPatch).length)
          memory.update(visitorPatch)

        const guidanceBlock = buildYXZGuidanceBlock(memory.state.value, intent)
        const yxzGuidance = guidanceBlock
          ? `${YXZ_SYSTEM_GUIDANCE}\n\n${guidanceBlock}`
          : YXZ_SYSTEM_GUIDANCE

        const first = newMessages[0]
        if (first?.role === 'system')
          newMessages[0] = { ...first, content: `${first.content}\n${yxzGuidance}` }
        else
          newMessages.unshift({ role: 'system', content: yxzGuidance })
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

      // A broken stream must not take the whole turn down.  The visitor is
      // standing in front of the screen: a silent, frozen chat looks like a
      // crash.  We keep the failure, finish the turn and say something.
      let streamFailure: Error | undefined
      try {
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
            // Every raw event proves the turn is alive.  The chat watchdog
            // watches this stamp instead of the visible text, so a model
            // that thinks for a while -- or a tool that renders images for
            // a minute -- is never mistaken for a frozen chat.
            chatStream.touchActivity()
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
                // Record it and let the stream wind down.  Throwing here
                // used to abort the whole turn, which is exactly the
                // "回答到一半就卡住" the visitor kept hitting.
                streamFailure = event.error ?? new Error('Stream error')
                console.error('[chat] stream reported an error', streamFailure)
                break
            }
          },
        })
      }
      catch (error) {
        streamFailure = error instanceof Error ? error : new Error(String(error))
        console.error('[chat] turn failed', streamFailure)
      }

      await parser.end()

      // Nothing was said and the stream broke: leave the visitor with a
      // short, usable reply instead of an empty bubble.
      if (streamFailure && !shouldAbort() && !fullText.trim()) {
        const fallback = '刚才这一轮没能连上，可能是网络抖了一下。你再说一次你的需求，我接着做。'
        buildingMessage.content = fallback
        buildingMessage.slices = [{ type: 'text', text: fallback }]
        updateUI()
      }

      // A turn that ends in a tool call can leave an assistant bubble that
      // holds nothing but a reasoning block.  When the turn produced a
      // creation card that card already carries the answer, so an empty
      // bubble underneath it only makes the conversation look stuck --
      // exactly what the visitor reported as "回完之后卡死".
      const spokeWords = buildingMessage.slices.some(slice => slice.type === 'text' && (slice.text ?? '').trim().length > 0)
      const producedCard = chatSession.getSessionMessages(sessionId)
        .slice(sessionMessagesForSend.length)
        .some(message => message.role === 'assistant' && (message.yxzCreation || message.yxzLaserCard))

      // The model sometimes ends a turn right after a tool call without
      // saying a word.  The visitor is left staring at an empty bubble
      // that looks exactly like the app froze, so the turn gets one
      // usable sentence instead.
      if (!spokeWords && !producedCard && !shouldAbort()) {
        const fallback = '刚才这一句我没接住。你可以再说一次，或者直接告诉我：是想调整刚才那版预览的造型和配色，还是直接做成 3D 模型？'
        buildingMessage.content = fallback
        buildingMessage.slices = [...buildingMessage.slices, { type: 'text', text: fallback }]
        updateUI()
      }

      const spokeAfterFallback = buildingMessage.slices.some(slice => slice.type === 'text' && (slice.text ?? '').trim().length > 0)
      if (!isStaleGeneration() && buildingMessage.slices.length > 0 && (spokeAfterFallback || !producedCard)) {
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
