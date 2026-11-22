import { describe, expect, it } from 'vitest'

import {
  buildYXZGuidanceBlock,
  extractYXZRequirementSignals,
  getYXZMissingRequirementSlots,
  isYXZRequirementReady,
  planYXZRequirementStep,
} from './use-yxz-guidance'
import type { YXZRequirementMemory } from './use-yxz-requirement-memory'

function memory(patch: Partial<YXZRequirementMemory> = {}): YXZRequirementMemory {
  return { description: '', constraints: [], updatedAt: 1, ...patch }
}

describe('yXZ requirement guidance', () => {
  it('asks for the subject before anything else', () => {
    const step = planYXZRequirementStep(memory())
    expect(step?.field).toBe('description')
    expect(step?.options?.length).toBeGreaterThan(0)
  })

  it('asks the visual slot that changes the drawing next', () => {
    const step = planYXZRequirementStep(memory({ description: '小熊摆件' }))
    expect(step?.field).toBe('style')
  })

  it('stops asking once the requirement is renderable', () => {
    const ready = memory({ description: '小熊摆件', style: '圆润可爱' })
    expect(isYXZRequirementReady(ready)).toBe(true)
    // Everything left has a default, so there is no next question.
    expect(planYXZRequirementStep(ready)).toBeNull()
  })

  it('treats plain constraints as a visual signal instead of asking again', () => {
    const withConstraints = memory({ description: '小熊摆件', constraints: ['不要文字'] })
    expect(isYXZRequirementReady(withConstraints)).toBe(true)
    expect(getYXZMissingRequirementSlots(withConstraints).some(slot => slot.field === 'style')).toBe(false)
  })

  it('renders the settled requirements and the defaults for the rest', () => {
    const block = buildYXZGuidanceBlock(memory({
      description: '宜小智机器人摆件',
      style: '圆润可爱',
      palette: '白色',
      constraints: ['无文字'],
    }))

    expect(block).toContain('【本次创作已确认的需求】')
    expect(block).toContain('做什么：宜小智机器人摆件')
    expect(block).toContain('风格：圆润可爱')
    expect(block).toContain('配色：白色')
    expect(block).toContain('其他要求：无文字')
    // Size and material have defaults, so they are stated, not asked.
    expect(block).toContain('【尚未确认，按默认处理即可】')
    expect(block).toContain('尺寸')
  })

  it('returns an empty block when nothing is known yet', () => {
    expect(buildYXZGuidanceBlock(null)).toBe('')
    expect(buildYXZGuidanceBlock(memory())).toBe('')
  })

  it('pulls style, colour and size out of free text', () => {
    const signals = extractYXZRequirementSignals('一个圆润可爱的白蓝配色小摆件，大概 9 厘米，放书桌上')
    expect(signals.style).toBe('圆润可爱')
    expect(signals.palette).toBe('白色')
    expect(signals.size).toBe('桌面款（约 9 cm）')
    expect(signals.purpose).toBe('桌面陈列')
  })

  it('does not invent slots the visitor never mentioned', () => {
    const signals = extractYXZRequirementSignals('一个普通的方块')
    expect(signals.style).toBeUndefined()
    expect(signals.palette).toBeUndefined()
    expect(signals.size).toBeUndefined()
  })
})
