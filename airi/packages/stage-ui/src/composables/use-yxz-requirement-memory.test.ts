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

  it('guides the next missing requirement instead of asking everything at once', () => {
    expect(getYXZRequirementNextQuestion(null)).toContain('什么')
    expect(getYXZRequirementNextQuestion({ description: '小熊', constraints: [], updatedAt: 1 })).toContain('放在哪里')
  })
})
