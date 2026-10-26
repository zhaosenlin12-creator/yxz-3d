import { ref } from 'vue'

export interface YXZRequirementMemory {
  description: string
  constraints: string[]
  style?: string
  audience?: string
  quantity?: number
  updatedAt: number
}

export interface YXZRequirementPatch {
  description?: string
  constraints?: string[]
  style?: string
  audience?: string
  quantity?: number
}

export interface YXZRequirementStorage {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

export const YXZ_REQUIREMENT_MEMORY_KEY = 'yxz/requirement-memory/v1'

function getDefaultStorage(): YXZRequirementStorage | undefined {
  if (typeof window === 'undefined' || !window.localStorage)
    return undefined

  return window.localStorage
}

function cleanText(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

function cleanConstraints(value: unknown) {
  if (!Array.isArray(value))
    return []

  return [...new Set(value.map(cleanText).filter(Boolean))]
}

export function normalizeYXZRequirementMemory(value: unknown): YXZRequirementMemory | null {
  if (!value || typeof value !== 'object')
    return null

  const record = value as Record<string, unknown>
  const description = cleanText(record.description)
  const constraints = cleanConstraints(record.constraints)
  if (!description && !constraints.length)
    return null

  const quantity = typeof record.quantity === 'number' && Number.isFinite(record.quantity) && record.quantity > 0
    ? Math.round(record.quantity)
    : undefined

  return {
    description,
    constraints,
    style: cleanText(record.style) || undefined,
    audience: cleanText(record.audience) || undefined,
    quantity,
    updatedAt: typeof record.updatedAt === 'number' && Number.isFinite(record.updatedAt) ? record.updatedAt : Date.now(),
  }
}

export function loadYXZRequirementMemory(storage = getDefaultStorage()) {
  if (!storage)
    return null

  try {
    const raw = storage.getItem(YXZ_REQUIREMENT_MEMORY_KEY)
    return raw ? normalizeYXZRequirementMemory(JSON.parse(raw)) : null
  }
  catch {
    return null
  }
}

export function mergeYXZRequirementMemory(current: YXZRequirementMemory | null, patch: YXZRequirementPatch): YXZRequirementMemory {
  const next = normalizeYXZRequirementMemory({
    ...current,
    ...patch,
    constraints: [...(current?.constraints ?? []), ...(patch.constraints ?? [])],
    updatedAt: Date.now(),
  })

  return next ?? {
    description: cleanText(patch.description),
    constraints: cleanConstraints(patch.constraints),
    style: cleanText(patch.style) || undefined,
    audience: cleanText(patch.audience) || undefined,
    quantity: patch.quantity,
    updatedAt: Date.now(),
  }
}

export function saveYXZRequirementMemory(memory: YXZRequirementMemory, storage = getDefaultStorage()) {
  if (!storage)
    return

  try {
    storage.setItem(YXZ_REQUIREMENT_MEMORY_KEY, JSON.stringify(memory))
  }
  catch {
    // Storage can be unavailable in private browsing or embedded webviews.
  }
}

export function clearYXZRequirementMemory(storage = getDefaultStorage()) {
  if (!storage)
    return

  try {
    storage.removeItem(YXZ_REQUIREMENT_MEMORY_KEY)
  }
  catch {
    // Ignore unavailable storage; the in-memory state is still cleared by the composable.
  }
}

export function getYXZRequirementNextQuestion(memory: YXZRequirementMemory | null) {
  if (!memory?.description)
    return '你想把什么做成宜小智作品？可以先说主题、角色或用途。'
  if (!memory.audience)
    return '这个作品主要放在哪里或送给谁？我会据此调整尺寸和细节。'
  if (!memory.style)
    return '你希望它更偏圆润可爱、简洁极简，还是保留更多辨识度？'
  if (!memory.quantity)
    return '需要制作几个？数量会影响后续打印安排。'
  return '需求已经比较完整，可以确认预览并进入 3D 制作。'
}

export function useYXZRequirementMemory(storage = getDefaultStorage()) {
  const state = ref<YXZRequirementMemory | null>(loadYXZRequirementMemory(storage))

  function update(patch: YXZRequirementPatch) {
    state.value = mergeYXZRequirementMemory(state.value, patch)
    saveYXZRequirementMemory(state.value, storage)
    return state.value
  }

  function clear() {
    state.value = null
    clearYXZRequirementMemory(storage)
  }

  return { state, update, clear }
}
