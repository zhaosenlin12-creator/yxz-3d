import type { Ref } from 'vue'

import { ref } from 'vue'

export interface YXZRequirementMemory {
  description: string
  constraints: string[]
  style?: string
  audience?: string
  quantity?: number
  /** What the piece is for — decides size and how much detail it carries. */
  purpose?: string
  /** Main colours. */
  palette?: string
  /** Printable size. */
  size?: string
  /** Print material / finish. */
  material?: string
  /** Which deliverable the visitor is heading for. */
  deliverable?: string
  /** The picture the visitor uploaded: the shape reference for the preview. */
  referenceImage?: YXZReferenceImage
  updatedAt: number
}

export interface YXZReferenceImage {
  sessionId: string
  path: string
  description: string
  width?: number
  height?: number
  /**
   * The chat session the picture was uploaded in.
   *
   * The picture is the shape reference for the *current* request.  Without
   * this marker a picture uploaded yesterday was still applied to today's
   * "make me a blue robot" -- the app then took the image-to-image route
   * with a picture the visitor never mentioned, which is slower and wrong.
   */
  chatSessionId?: string
}

export interface YXZRequirementPatch {
  description?: string
  constraints?: string[]
  style?: string
  audience?: string
  quantity?: number
  purpose?: string
  palette?: string
  size?: string
  material?: string
  deliverable?: string
  referenceImage?: YXZReferenceImage | null
}

export interface YXZRequirementStorage {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

export const YXZ_REQUIREMENT_MEMORY_KEY = 'yxz/requirement-memory/v1'

const sharedStates = new Map<YXZRequirementStorage | undefined, Ref<YXZRequirementMemory | null>>()

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

function cleanReferenceImage(value: unknown): YXZReferenceImage | undefined {
  if (!value || typeof value !== 'object')
    return undefined

  const record = value as Record<string, unknown>
  const sessionId = cleanText(record.sessionId)
  const path = cleanText(record.path)
  if (!sessionId || !path)
    return undefined

  const width = typeof record.width === 'number' && Number.isFinite(record.width) ? record.width : undefined
  const height = typeof record.height === 'number' && Number.isFinite(record.height) ? record.height : undefined
  const chatSessionId = cleanText(record.chatSessionId)
  return {
    sessionId,
    path,
    description: cleanText(record.description),
    width,
    height,
    chatSessionId: chatSessionId || undefined,
  }
}

export function normalizeYXZRequirementMemory(value: unknown): YXZRequirementMemory | null {
  if (!value || typeof value !== 'object')
    return null

  const record = value as Record<string, unknown>
  const description = cleanText(record.description)
  const constraints = cleanConstraints(record.constraints)
  const referenceImage = cleanReferenceImage(record.referenceImage)
  if (!description && !constraints.length && !referenceImage)
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
    purpose: cleanText(record.purpose) || undefined,
    palette: cleanText(record.palette) || undefined,
    size: cleanText(record.size) || undefined,
    material: cleanText(record.material) || undefined,
    deliverable: cleanText(record.deliverable) || undefined,
    referenceImage,
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
    referenceImage: patch.referenceImage === null ? undefined : (patch.referenceImage ?? current?.referenceImage),
    updatedAt: Date.now(),
  })

  return next ?? {
    description: cleanText(patch.description),
    constraints: cleanConstraints(patch.constraints),
    style: cleanText(patch.style) || undefined,
    audience: cleanText(patch.audience) || undefined,
    quantity: patch.quantity,
    purpose: cleanText(patch.purpose) || undefined,
    palette: cleanText(patch.palette) || undefined,
    size: cleanText(patch.size) || undefined,
    material: cleanText(patch.material) || undefined,
    deliverable: cleanText(patch.deliverable) || undefined,
    referenceImage: patch.referenceImage === null ? undefined : patch.referenceImage,
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

// The question plan lives in use-yxz-guidance.ts, next to the slot table that
// explains *why* each question is asked and in which order. It is re-exported
// here so the existing callers keep working unchanged.
export { getYXZRequirementNextQuestion } from './use-yxz-guidance'

export function useYXZRequirementMemory(storage = getDefaultStorage()) {
  // Several surfaces touch the same memory (the chat panel, the guided
  // preview panel and the creation tool).  Keeping one ref per storage
  // means an update made in one place is visible in the others right away
  // instead of landing on a stale snapshot.
  let shared = sharedStates.get(storage)
  if (!shared) {
    shared = ref<YXZRequirementMemory | null>(loadYXZRequirementMemory(storage))
    sharedStates.set(storage, shared)
  }
  const state = shared

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
