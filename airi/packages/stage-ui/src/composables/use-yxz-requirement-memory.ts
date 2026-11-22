import type { Ref } from 'vue'

import { computed, ref } from 'vue'

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
  /**
   * The conversation this memory belongs to.
   *
   * The memory used to be one global blob in localStorage, so the style
   * a visitor asked for yesterday followed them into today's request and
   * the assistant looked like it was answering somebody else.  Every
   * conversation now keeps its own memory.
   */
  chatSessionId?: string
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

/**
 * The conversation the memory currently belongs to.
 *
 * Every conversation keeps its own memory, so starting a new one starts
 * with a clean sheet.  The chat store keeps this in sync with the active
 * session; the panels and tools read it so they all see the same thing.
 */
export const YXZ_DEFAULT_REQUIREMENT_SCOPE = 'global'

export const yxzRequirementScope = ref<string>(YXZ_DEFAULT_REQUIREMENT_SCOPE)

export function setYXZRequirementScope(scopeId?: string | null) {
  const next = resolveScope(scopeId)
  if (yxzRequirementScope.value !== next)
    yxzRequirementScope.value = next
}

function resolveScope(scopeId?: string | null) {
  return (scopeId ?? '').trim() || YXZ_DEFAULT_REQUIREMENT_SCOPE
}

/** How many conversations keep their own memory around. */
const YXZ_MAX_REMEMBERED_SCOPES = 12

const scopedStates = new Map<YXZRequirementStorage | undefined, Map<string, Ref<YXZRequirementMemory | null>>>()

/**
 * Which conversation owns the memory that predates the per-conversation
 * split.  It is claimed once, by the first conversation that asks for it,
 * so a stale global memory can never leak into a second conversation.
 */
let legacyOwner: string | null = null

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
    chatSessionId: cleanText(record.chatSessionId) || undefined,
  }
}

interface YXZScopeStore {
  scopes: Record<string, YXZRequirementMemory>
  /** Memory written before conversations were separated. */
  legacy?: YXZRequirementMemory
}

function readScopeStore(storage: YXZRequirementStorage | undefined): YXZScopeStore | null {
  if (!storage)
    return null

  try {
    const raw = storage.getItem(YXZ_REQUIREMENT_MEMORY_KEY)
    if (!raw)
      return null

    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object')
      return null

    const record = parsed as Record<string, unknown>
    if (record.version === 2 && record.scopes && typeof record.scopes === 'object') {
      const scopes: Record<string, YXZRequirementMemory> = {}
      for (const [key, value] of Object.entries(record.scopes as Record<string, unknown>)) {
        const memory = normalizeYXZRequirementMemory(value)
        if (memory)
          scopes[key] = memory
      }
      return { scopes }
    }

    // The old format: one flat memory shared by every conversation.
    const legacy = normalizeYXZRequirementMemory(record)
    return legacy ? { scopes: {}, legacy } : { scopes: {} }
  }
  catch {
    return null
  }
}

function writeScopeStore(storage: YXZRequirementStorage | undefined, store: YXZScopeStore) {
  if (!storage)
    return

  try {
    storage.setItem(YXZ_REQUIREMENT_MEMORY_KEY, JSON.stringify({ version: 2, scopes: store.scopes }))
  }
  catch {
    // Storage can be unavailable in private browsing or embedded webviews.
  }
}

export function loadYXZRequirementMemory(storage = getDefaultStorage(), scopeId?: string) {
  const scope = resolveScope(scopeId ?? yxzRequirementScope.value)
  const store = readScopeStore(storage)
  if (!store)
    return null

  const scoped = store.scopes[scope]
  if (scoped)
    return scoped

  if (!store.legacy)
    return null

  // The pre-split memory belongs to one conversation only: the first one
  // that asks for it.  Everybody else starts clean.
  if (legacyOwner === null)
    legacyOwner = scope
  if (legacyOwner !== scope)
    return null

  return store.legacy
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

export function saveYXZRequirementMemory(memory: YXZRequirementMemory, storage = getDefaultStorage(), scopeId?: string) {
  const scope = resolveScope(scopeId ?? yxzRequirementScope.value)
  const store = readScopeStore(storage) ?? { scopes: {} }
  const scopes: Record<string, YXZRequirementMemory> = { ...store.scopes }

  scopes[scope] = {
    ...memory,
    chatSessionId: scope === YXZ_DEFAULT_REQUIREMENT_SCOPE ? undefined : scope,
  }

  // The pre-split memory is pinned to the conversation that claimed it
  // instead of floating between all of them.
  if (store.legacy && legacyOwner && !scopes[legacyOwner])
    scopes[legacyOwner] = store.legacy

  const kept = Object.entries(scopes)
    .sort((a, b) => (b[1].updatedAt ?? 0) - (a[1].updatedAt ?? 0))
    .slice(0, YXZ_MAX_REMEMBERED_SCOPES)

  writeScopeStore(storage, { scopes: Object.fromEntries(kept) })
}

export function clearYXZRequirementMemory(storage = getDefaultStorage(), scopeId?: string) {
  const scope = resolveScope(scopeId ?? yxzRequirementScope.value)
  const store = readScopeStore(storage)
  if (!store)
    return

  const scopes = { ...store.scopes }
  delete scopes[scope]
  writeScopeStore(storage, { scopes })
}

// The question plan lives in use-yxz-guidance.ts, next to the slot table that
// explains *why* each question is asked and in which order. It is re-exported
// here so the existing callers keep working unchanged.
export { getYXZRequirementNextQuestion } from './use-yxz-guidance'

export function useYXZRequirementMemory(storage = getDefaultStorage()) {
  // Several surfaces touch the same memory (the chat panel, the guided
  // preview panel and the creation tool).  Keeping one ref per storage and
  // scope means an update made in one place is visible in the others right
  // away instead of landing on a stale snapshot.
  const scopedState = (scope: string) => {
    const scopeId = resolveScope(scope)
    let byScope = scopedStates.get(storage)
    if (!byScope) {
      byScope = new Map<string, Ref<YXZRequirementMemory | null>>()
      scopedStates.set(storage, byScope)
    }

    let state = byScope.get(scopeId)
    if (!state) {
      state = ref<YXZRequirementMemory | null>(loadYXZRequirementMemory(storage, scopeId))
      byScope.set(scopeId, state)
    }
    return state
  }

  // The active conversation decides which memory is visible, so switching
  // conversations swaps the whole memory over -- including in the panels
  // that only ever read `.value`.
  const state = computed(() => scopedState(yxzRequirementScope.value).value)

  function update(patch: YXZRequirementPatch, scope: string = yxzRequirementScope.value) {
    const scopeId = resolveScope(scope)
    const target = scopedState(scopeId)
    target.value = mergeYXZRequirementMemory(target.value, patch)
    saveYXZRequirementMemory(target.value, storage, scopeId)
    return target.value
  }

  function clear(scope: string = yxzRequirementScope.value) {
    const scopeId = resolveScope(scope)
    const target = scopedState(scopeId)
    target.value = null
    clearYXZRequirementMemory(storage, scopeId)
  }

  /** The memory of one specific conversation. */
  function stateFor(scope: string) {
    return scopedState(scope).value
  }

  return { state, stateFor, update, clear }
}
