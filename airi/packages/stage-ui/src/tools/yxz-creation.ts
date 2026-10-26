import type { YXZModelResponse } from '../composables/use-yxz-print-preview'
import type { ChatAssistantMessage } from '../types/chat'

import { tool } from '@xsai/tool'
import { nanoid } from 'nanoid'
import { z } from 'zod'

import { buildYXZPreviewPrompt, createYXZCartoonModel, createYXZPreview, getYXZPrintApiBase, previewImageSrc } from '../composables/use-yxz-print-preview'
import { useYXZRequirementMemory } from '../composables/use-yxz-requirement-memory'
import { useChatSessionStore } from '../stores/chat/session-store'

const YXZ_MODEL_CONFIRMATION_RE = /生成|制作|做成|开始|确认|同意|可以|继续|好/

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
      description: '宜小智专用：用户要制作激光切割名片、卡片、桌牌等平面切割物料（尤其活动名片）时调用。预制模板：背面固定活动宣传图，正面编辑姓名/职位/单位/联系方式。生成后引导用户在输入框左侧 + 号继续编辑或下载切割文件。',
      parameters: z.object({
        name: z.string().min(1).max(12).describe('名片上的姓名'),
        title: z.string().max(20).describe('职位，可空'),
        unit: z.string().max(30).describe('单位或机构名，可空'),
        contact: z.string().max(120).describe('联系方式，多行（电话/微信/邮箱），可空'),
        slogan: z.string().max(30).describe('名片标语，默认“数理创未来 智慧启新程”'),
      }).strict(),
      execute: async ({ name, title, unit, contact, slogan }) => {
        const base = getYXZPrintApiBase()
        const payload = {
          name,
          title: title ?? '',
          unit: unit ?? '',
          contact: contact ?? '',
          slogan: slogan || '数理创未来 智慧启新程',
          theme: '#0B5FA8',
          accent: '#F5A623',
          bg_style: 'gradient',
          back_template: 'activity_blue',
          back_caption: '宜昌市第四届中小学生数理文化活动',
          note: '',
        }
        let response: Response
        try {
          response = await fetch(`${base}/api/laser_card`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          })
        }
        catch {
          throw new Error('激光名片服务暂时不可用，请确认后端服务已启动，或稍后重试')
        }
        const raw: unknown = await response.json().catch(() => undefined)
        if (!response.ok) {
          const detail = (raw as { detail?: string })?.detail
          throw new Error(detail || `名片生成失败（HTTP ${response.status}）`)
        }
        const data = raw as { session_id: string, svg_url: string, png_url: string }
        return {
          status: 'laser-card-ready',
          sessionId: data.session_id,
          pngUrl: `${base}${data.png_url}`,
          svgUrl: `${base}${data.svg_url}`,
          message: '名片已生成。请在预览确认后，点输入框左侧的 + 号打开「激光切割名片」继续编辑或生成切割文件；如需调整姓名、联系方式等内容，告诉我即可。',
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
