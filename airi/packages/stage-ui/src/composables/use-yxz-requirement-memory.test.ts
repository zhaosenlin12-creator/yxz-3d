import { describe, expect, it } from 'vitest'

import {
  clearYXZRequirementMemory,
  getYXZRequirementNextQuestion,
  loadYXZRequirementMemory,
  mergeYXZRequirementMemory,
  saveYXZRequirementMemory,
  YXZ_REQUIREMENT_MEMORY_KEY,
} from './use-yxz-requirement-memory'

function createStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  }
}

describe('yXZ requirement memory', () => {
  it('merges and deduplicates constraints across turns', () => {
    const first = mergeYXZRequirementMemory(null, { description: '小熊摆件', constraints: ['圆润可爱'] })
    const next = mergeYXZRequirementMemory(first, { constraints: ['圆润可爱', '适合 3D 打印'], audience: '桌面' })

    expect(next.description).toBe('小熊摆件')
    expect(next.constraints).toEqual(['圆润可爱', '适合 3D 打印'])
    expect(next.audience).toBe('桌面')
  })

  it('persists, loads, and clears browser-safe storage', () => {
    const storage = createStorage()
    const memory = mergeYXZRequirementMemory(null, { description: '猫咪', constraints: ['单色模型'] })
    saveYXZRequirementMemory(memory, storage)

    expect(storage.getItem(YXZ_REQUIREMENT_MEMORY_KEY)).toBeTruthy()
    expect(loadYXZRequirementMemory(storage)?.description).toBe('猫咪')
    clearYXZRequirementMemory(storage)
    expect(loadYXZRequirementMemory(storage)).toBeNull()
  })

  it('keeps every conversation in its own memory', () => {
    const storage = createStorage()
    const yesterday = mergeYXZRequirementMemory(null, { description: '圆润可爱的小熊', style: '圆润可爱' })
    saveYXZRequirementMemory(yesterday, storage, 'session-a')

    const today = mergeYXZRequirementMemory(null, { description: '蓝色机器人' })
    saveYXZRequirementMemory(today, storage, 'session-b')

    // Yesterday's style must not follow the visitor into a new chat.
    expect(loadYXZRequirementMemory(storage, 'session-a')?.style).toBe('圆润可爱')
    expect(loadYXZRequirementMemory(storage, 'session-b')?.style).toBeUndefined()
    expect(loadYXZRequirementMemory(storage, 'session-b')?.description).toBe('蓝色机器人')

    // A conversation nobody has used yet starts clean.
    expect(loadYXZRequirementMemory(storage, 'session-c')).toBeNull()
  })

  it('gives the old global memory to one conversation only', () => {
    const storage = createStorage()
    // The format before conversations were separated.
    storage.setItem(YXZ_REQUIREMENT_MEMORY_KEY, JSON.stringify({
      description: '小熊',
      constraints: ['圆润'],
      updatedAt: 1,
    }))

    expect(loadYXZRequirementMemory(storage, 'session-a')?.description).toBe('小熊')
    // The second conversation must not inherit it.
    expect(loadYXZRequirementMemory(storage, 'session-b')).toBeNull()
  })

  it('guides the next missing requirement instead of asking everything at once', () => {
    expect(getYXZRequirementNextQuestion(null)).toContain('什么')
    // The subject alone is not enough: the next thing worth asking is the
    // one that changes the drawing most, which is the style.
    expect(getYXZRequirementNextQuestion({ description: '小熊', constraints: [], updatedAt: 1 })).toContain('圆润可爱')
    // Once the look is settled the plan is done -- asking more would be
    // an interview instead of a conversation.
    const settled = mergeYXZRequirementMemory(null, { description: '小熊', style: '圆润可爱' })
    expect(getYXZRequirementNextQuestion(settled)).toContain('确认预览')
  })
})
