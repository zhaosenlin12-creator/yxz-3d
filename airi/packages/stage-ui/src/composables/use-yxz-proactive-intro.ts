import type { ChatHistoryItem } from '../types/chat'

export const YXZ_PROACTIVE_INTRO_ID = 'yxz-proactive-intro'
export const YXZ_PROACTIVE_INTRO_TEXT = '你好，我是宜小智，你的 AI 智能创造伙伴。你可以直接告诉我想做的产品，我会一步步帮你完善方案、生成预览，再进入 3D 制作。今天最想做什么？'

export function createYXZProactiveIntro(createdAt = Date.now()): ChatHistoryItem {
  return {
    role: 'assistant',
    content: YXZ_PROACTIVE_INTRO_TEXT,
    slices: [{ type: 'text', text: YXZ_PROACTIVE_INTRO_TEXT }],
    tool_results: [],
    createdAt,
    id: YXZ_PROACTIVE_INTRO_ID,
  }
}

export function ensureYXZProactiveIntro(messages: ChatHistoryItem[], createdAt = Date.now()) {
  const existingIndex = messages.findIndex(message => message.id === YXZ_PROACTIVE_INTRO_ID)
  if (existingIndex >= 0) {
    const existing = messages[existingIndex]
    if (existing?.content === YXZ_PROACTIVE_INTRO_TEXT)
      return { messages, added: false }

    const refreshed = createYXZProactiveIntro(existing?.createdAt ?? createdAt)
    const next = [...messages]
    next[existingIndex] = refreshed
    return { messages: next, added: false }
  }

  return {
    messages: [...messages, createYXZProactiveIntro(createdAt)],
    added: true,
  }
}
