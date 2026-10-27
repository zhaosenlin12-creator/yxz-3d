import type { YXZModelResponse } from '../composables/use-yxz-print-preview'
import type { ChatAssistantMessage } from '../types/chat'

import { tool } from '@xsai/tool'
import { nanoid } from 'nanoid'
import { z } from 'zod'

import { buildYXZPreviewPrompt, createYXZCartoonModel, createYXZLaserCard, createYXZPreview, previewImageSrc } from '../composables/use-yxz-print-preview'
import { useYXZRequirementMemory } from '../composables/use-yxz-requirement-memory'
import { useChatSessionStore } from '../stores/chat/session-store'

const YXZ_MODEL_CONFIRMATION_RE = /生成|制作|做成|开始|确认|同意|可以|继续|好/

function appendLaserCardCard(input: {
  sessionId: string
  svgUrl: string
  pngUrl: string
  frontUrl: string
  backUrl: string
  sizeMm: { width: number, height: number }
  backTemplate: string
  artworkSessionId?: string
  artworkImageIndex?: number
  name?: string
  description?: string
  hasArtwork: boolean
}) {
  const sessions = useChatSessionStore()
  const sessionId = sessions.activeSessionId
  if (!sessionId)
    return

  const messages = sessions.getSessionMessages(sessionId)
  const existingIndex = messages.findIndex(message => message.role === 'assistant'
    && message.yxzLaserCard?.kind === 'yxz-laser-card'
    && message.yxzLaserCard.sessionId === input.sessionId)
  const content = '激光切割卡片已生成：卡片正面是你的作品，背面是活动主视觉背景，可直接用 xTool 打开切割文件。'
  const message = {
    role: 'assistant' as const,
    content,
    slices: [{ type: 'text' as const, text: content }],
    tool_results: [],
    yxzLaserCard: {
      kind: 'yxz-laser-card' as const,
      ...input,
    },
    createdAt: Date.now(),
    id: existingIndex >= 0 ? messages[existingIndex].id : nanoid(),
  }
  if (existingIndex >= 0) {
    const next = [...messages]
    next[existingIndex] = message
    sessions.setSessionMessages(sessionId, next)
  }
  else {
    sessions.appendSessionMessage(sessionId, message)
  }
}

function appendCreationCard(input: {
  sessionId?: string
  description: string
  options: string[]
  preview: { index: number, src: string, caption: string }
  previews?: Array<{ index: number, src: string, caption: string }>
  model?: { modelUrl: string, stlUrl: string, glbUrl: string }
  status: 'preview' | 'model-building' | 'model-ready'
  progressMsg?: string
}) {
  const sessions = useChatSessionStore()
  const sessionId = sessions.activeSessionId
  if (!sessionId)
    return

  const messages = sessions.getSessionMessages(sessionId)
  const existingIndex = messages.findIndex(message => message.role === 'assistant'
    && message.yxzCreation?.kind === 'yxz-creation'
    && message.yxzCreation.preview.src === input.preview.src)
  const content = input.status === 'model-ready'
    ? '3D 模型已完成，请查看方案卡片。'
    : input.status === 'model-building'
      ? (input.progressMsg || '正在制作 3D 模型，请耐心等待…')
      : '预览已生成，请查看方案卡片。'
  const message = {
    role: 'assistant' as const,
    content,
    slices: [{ type: 'text' as const, text: content }],
    tool_results: [],
    yxzCreation: {
      kind: 'yxz-creation' as const,
      sessionId: input.sessionId,
      description: input.description,
      options: input.options,
      preview: input.preview,
      previews: input.previews,
      model: input.model,
      status: input.status,
      progressMsg: input.progressMsg,
    },
    createdAt: Date.now(),
    id: existingIndex >= 0 ? messages[existingIndex].id : nanoid(),
  }
  if (existingIndex >= 0) {
    const next = [...messages]
    next[existingIndex] = message
    sessions.setSessionMessages(sessionId, next)
  }
  else {
    sessions.appendSessionMessage(sessionId, message)
  }
}

/**
 * Deterministic confirmation path for the exhibition preset.
 *
 * Some local/compatible chat providers return a plain assistant turn instead
 * of emitting a tool call even though the user explicitly approved the
 * preview. The UI must not leave the visitor at a dead end in that case, so
 * the preset can call the same backend operation directly after validating
 * the latest preview card and confirmation text.
 */
export async function generateYXZModelFromConfirmation(sessionId: string, userText: string): Promise<{
  result: YXZModelResponse
  message: string
}> {
  const sessions = useChatSessionStore()
  const activeSessionId = sessions.activeSessionId
  if (!activeSessionId)
    throw new Error('当前没有可用的宜小智会话')

  const messages = sessions.getSessionMessages(activeSessionId)
  const card = [...messages].reverse().find((message): message is ChatAssistantMessage & { createdAt?: number } => message.role === 'assistant'
    && message.yxzCreation?.kind === 'yxz-creation'
    && message.yxzCreation.status === 'preview')
  if (!card?.yxzCreation)
    throw new Error('请先在当前对话生成预览图')

  if (!YXZ_MODEL_CONFIRMATION_RE.test(userText))
    throw new Error('请先明确确认制作 3D 模型')
  // The caller normally supplies the active chat-session id. A tool caller
  // may instead pass the preview backend session id, so accept either while
  // always using the id stored on the validated preview card for generation.
  if (!card.yxzCreation.sessionId || (sessionId !== activeSessionId && sessionId !== card.yxzCreation.sessionId))
    throw new Error('预览会话已失效，请重新生成预览')

  appendCreationCard({
    sessionId: card.yxzCreation.sessionId,
    description: card.yxzCreation.description,
    options: card.yxzCreation.options,
    preview: card.yxzCreation.preview,
    status: 'model-building',
  })
  const result = await createYXZCartoonModel({
    sessionId: card.yxzCreation.sessionId,
    imageIndex: card.yxzCreation.preview.index,
    onProgress: progress => appendCreationCard({
      sessionId: card.yxzCreation.sessionId,
      description: card.yxzCreation.description,
      options: card.yxzCreation.options,
      preview: card.yxzCreation.preview,
      status: 'model-building',
      progressMsg: progress.message,
    }),
  })
  appendCreationCard({
    sessionId: card.yxzCreation.sessionId,
    description: card.yxzCreation.description,
    options: card.yxzCreation.options,
    preview: card.yxzCreation.preview,
    model: result,
    status: 'model-ready',
  })
  return {
    result,
    message: '3D 模型已完成，请查看方案卡片。',
  }
}

export async function createYXZCreationTools() {
  return Promise.all([
    tool({
      name: 'yxz_laserCard',
      description: '宜小智专用：用户要做激光切割卡片（活动名片 / 作品卡 / 桌牌等平面切割物料）时调用。卡片尺寸固定、背面是活动主视觉背景图，正面是用户自己的作品预览图（先用 yxz_generatePreview 生成）。请在用户已确认作品与个人信息（姓名 / 身份 / 单位 / 联系方式）之后再调用；若还没有作品预览图，先调用 yxz_generatePreview。',
      parameters: z.object({
        name: z.string().min(1).max(12).describe('卡片正面的姓名'),
        title: z.string().max(20).describe('身份/职位，可空'),
        unit: z.string().max(30).describe('学校或单位名，可空'),
        contact: z.string().max(120).describe('联系方式（电话/微信/邮箱），可空'),
        slogan: z.string().max(30).describe('卡片标语，默认“数理创未来 智慧启新程”'),
        previewSessionId: z.string().max(40).describe('作品预览会话 id（yxz_generatePreview 返回的 sessionId），作为卡片正面图；没有则留空'),
        previewImageIndex: z.number().int().min(0).max(9).describe('作品预览图序号，默认 0'),
      }).strict(),
      execute: async ({ name, title, unit, contact, slogan, previewSessionId, previewImageIndex }) => {
        const artworkSessionId = (previewSessionId ?? '').trim()
        const artworkImageIndex = previewImageIndex ?? 0
        let result: Awaited<ReturnType<typeof createYXZLaserCard>>
        try {
          result = await createYXZLaserCard({
            sessionId: artworkSessionId ? `${artworkSessionId}_card` : undefined,
            artworkSessionId: artworkSessionId || undefined,
            artworkImageIndex,
            name,
            title,
            unit,
            contact,
            slogan,
          })
        }
        catch (error) {
          throw new Error(error instanceof Error ? error.message : '激光切割卡片生成失败，请稍后重试')
        }
        appendLaserCardCard({
          sessionId: result.sessionId,
          svgUrl: result.svgUrl,
          pngUrl: result.pngUrl,
          frontUrl: result.frontUrl,
          backUrl: result.backUrl,
          sizeMm: result.sizeMm,
          backTemplate: result.backTemplate,
          artworkSessionId: artworkSessionId || undefined,
          artworkImageIndex,
          name,
          description: [title, unit].filter(Boolean).join(' · '),
          hasArtwork: result.hasArtwork,
        })
        return {
          status: 'laser-card-ready',
          sessionId: result.sessionId,
          pngUrl: result.pngUrl,
          svgUrl: result.svgUrl,
          message: result.hasArtwork
            ? '卡片已生成：正面是你的作品预览图，背面是活动背景。可在预览卡里下载切割 SVG、用 xTool 打开切割，或点「打开创作面板」继续编辑并产出 3D 效果。'
            : '卡片已生成：背面是活动背景，正面是姓名信息卡。可在预览卡里下载切割 SVG 或用 xTool 打开切割；也可以先让我生成作品预览图，把作品放到卡片正面。',
        }
      },
    }),
    tool({
      name: 'yxz_generatePreview',
      description: '宜小智专用：在用户说清产品、用途和主要风格后，直接调用已连接的 3D 打印后台生成产品预览图。不要要求用户手动点“开始创作”。一次生成 4 张备选预览，结果会自动出现在聊天卡片，用户可点图放大、切换查看。',
      parameters: z.object({
        description: z.string().min(3).max(500).describe('中文产品描述，包含对象、用途、关键造型'),
        constraints: z.array(z.string()).max(8).describe('用户已确认的风格、尺寸、颜色和打印约束'),
      }).strict(),
      execute: async ({ description, constraints }) => {
        const memory = useYXZRequirementMemory()
        memory.update({ description, constraints })
        const result = await createYXZPreview({
          prompt: buildYXZPreviewPrompt(description, constraints),
          n: 4,
        })
        const item = result.previews[0]
        if (!item)
          throw new Error('后台没有返回预览图')
        const toCard = (it: typeof item) => ({
          index: it.index,
          src: previewImageSrc(it.path ? { ...it, b64: undefined } : it),
          caption: it.caption || '产品预览',
        })
        const preview = toCard(item)
        const previews = result.previews.map(toCard)
        appendCreationCard({ sessionId: result.sessionId, description, options: constraints, preview, previews, status: 'preview' })
        return {
          status: 'preview-ready',
          sessionId: result.sessionId,
          imageIndex: preview.index,
          previewUrl: preview.src,
          message: '预览图已在聊天中展示。请询问用户是否采用并生成 3D 模型。',
        }
      },
    }),
    tool({
      name: 'yxz_generate3DModel',
      description: '宜小智专用：仅当用户看到预览并明确同意制作 3D 模型时调用。调用已连接的打印后台生成 GLB/STL；不要谎称没有 3D 能力，也不要自动启动打印机。',
      parameters: z.object({
        sessionId: z.string().min(1).describe('yxz_generatePreview 返回的 sessionId'),
        imageIndex: z.number().int().min(0).describe('yxz_generatePreview 返回的 imageIndex'),
      }).strict(),
      execute: async ({ sessionId, imageIndex }) => {
        const sessions = useChatSessionStore()
        const messages = sessions.getSessionMessages(sessions.activeSessionId)
        const card = [...messages].reverse().find((message): message is ChatAssistantMessage & { createdAt?: number } => message.role === 'assistant'
          && message.yxzCreation?.kind === 'yxz-creation'
          && message.yxzCreation.status === 'preview'
          && message.yxzCreation.preview.index === imageIndex)
        if (!card?.yxzCreation)
          throw new Error('请先在当前对话生成并确认预览图')
        const latestUser = [...messages].reverse().find(message => message.role === 'user')
        const userText = typeof latestUser?.content === 'string' ? latestUser.content : ''
        const cardCreatedAt = card.createdAt ?? 0
        if (!latestUser || (latestUser.createdAt ?? 0) <= cardCreatedAt)
          throw new Error('请先查看预览，再回复是否制作 3D 模型')
        if (!YXZ_MODEL_CONFIRMATION_RE.test(userText))
          throw new Error('请先让用户明确确认制作 3D 模型')
        if (!card.yxzCreation.sessionId || card.yxzCreation.sessionId !== sessionId)
          throw new Error('预览会话已失效，请重新生成预览')
        appendCreationCard({
          sessionId: card.yxzCreation.sessionId,
          description: card.yxzCreation.description,
          options: card.yxzCreation.options,
          preview: card.yxzCreation.preview,
          status: 'model-building',
        })
        const result = await createYXZCartoonModel({
          sessionId: card.yxzCreation.sessionId,
          imageIndex,
          onProgress: progress => appendCreationCard({
            sessionId: card.yxzCreation.sessionId,
            description: card.yxzCreation.description,
            options: card.yxzCreation.options,
            preview: card.yxzCreation.preview,
            status: 'model-building',
            progressMsg: progress.message,
          }),
        })
        appendCreationCard({
          sessionId: card.yxzCreation.sessionId,
          description: card.yxzCreation.description,
          options: card.yxzCreation.options,
          preview: card.yxzCreation.preview,
          model: result,
          status: 'model-ready',
        })
        return {
          status: 'model-ready',
          glbUrl: result.glbUrl,
          stlUrl: result.stlUrl,
          message: '3D 模型已在聊天卡片中提供预览和下载。打印机尚未自动启动。',
        }
      },
    }),
  ])
}
