import { describe, expect, it } from 'vitest'

import {
  buildYXZClarificationReply,
  buildYXZGuidanceBlock,
  classifyYXZVisitorIntent,
  extractYXZRequirementSignals,
  extractYXZVisitorPatch,
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

describe('yXZ visitor intent', () => {
  it('reads a complaint as a complaint, not as "draw it again"', () => {
    expect(classifyYXZVisitorIntent('你???')).toBe('confused')
    expect(classifyYXZVisitorIntent('怎么还没好')).toBe('confused')
    expect(classifyYXZVisitorIntent('啥情况')).toBe('confused')
    expect(classifyYXZVisitorIntent('不是这个')).toBe('confused')
  })

  it('reads "again please" as a redraw', () => {
    expect(classifyYXZVisitorIntent('再出一次')).toBe('regenerate')
    expect(classifyYXZVisitorIntent('换一批看看')).toBe('regenerate')
    expect(classifyYXZVisitorIntent('重新生成')).toBe('regenerate')
  })

  it('reads a product request as a requirement even when it ends with a question mark', () => {
    expect(classifyYXZVisitorIntent('能帮我做个圣诞树摆件吗')).toBe('new-requirement')
    expect(classifyYXZVisitorIntent('我想做一个可爱的桌面小猫摆件')).toBe('new-requirement')
  })

  it('reads a plain question as a question', () => {
    expect(classifyYXZVisitorIntent('展台是几点开始')).toBe('question')
  })

  it('reads a question about the making as a question, not as a brief', () => {
    expect(classifyYXZVisitorIntent('打印要多久')).toBe('question')
    expect(classifyYXZVisitorIntent('3D打印多长时间能好')).toBe('question')
    expect(classifyYXZVisitorIntent('这个要多少钱')).toBe('question')
  })

  it('reads a colour change as a change, not as a question', () => {
    expect(classifyYXZVisitorIntent('换成蓝色可以吗')).toBe('refine')
    expect(classifyYXZVisitorIntent('颜色要深一点')).toBe('refine')
  })

  it('still reads a brief that names a colour as a brief', () => {
    expect(classifyYXZVisitorIntent('我要做一个蓝色的摆件')).toBe('new-requirement')
  })

  it('keeps the brief when a complaint carries one', () => {
    expect(classifyYXZVisitorIntent('怎么还没好，我要个小熊')).toBe('new-requirement')
    // An explicit redraw wins: the visitor said what they want.
    expect(classifyYXZVisitorIntent('不是这个，我要重新生成')).toBe('regenerate')
  })

  it('still reads a bare complaint as a complaint', () => {
    expect(classifyYXZVisitorIntent('你???')).toBe('confused')
    expect(classifyYXZVisitorIntent('怎么还没好')).toBe('confused')
    expect(classifyYXZVisitorIntent('不是这个')).toBe('confused')
  })

  it('keeps a complaint out of the requirement memory', () => {
    const patch = extractYXZVisitorPatch('你???', 'confused')
    expect(Object.keys(patch)).toHaveLength(0)
  })

  it('remembers what the visitor said about the look', () => {
    const patch = extractYXZVisitorPatch('圆润可爱，不要文字', 'new-requirement')
    expect(patch.style).toBe('圆润可爱')
    expect(patch.constraints).toEqual(['圆润可爱，不要文字'])
  })

  it('does not let a complaint overwrite the confirmed subject', () => {
    const patch = extractYXZVisitorPatch('你???', 'confused')
    expect(patch.description).toBeUndefined()
  })

  it('tells the model what the message means', () => {
    const block = buildYXZGuidanceBlock(null, 'confused')
    expect(block).toContain('【访客这句的意思】')
    expect(block).toContain('不要自作主张重新出图')
  })
})

describe('yXZ clarification of a confused visitor', () => {
  it('says the preview is there when it is', () => {
    const reply = buildYXZClarificationReply({ hasPreview: true, isBuilding: false })
    expect(reply).toContain('预览已经出来了')
  })

  it('never claims a preview that is not on screen', () => {
    const reply = buildYXZClarificationReply({ hasPreview: false, isBuilding: false, description: '小熊摆件' })
    expect(reply).not.toContain('预览已经出来了')
    expect(reply).toContain('小熊摆件')
  })

  it('tells the visitor the picture is still being made', () => {
    const reply = buildYXZClarificationReply({ hasPreview: false, isBuilding: true })
    expect(reply).toContain('还在生成中')
  })

  it('asks what to make when nothing is known yet', () => {
    const reply = buildYXZClarificationReply({ hasPreview: false, isBuilding: false })
    expect(reply).toContain('你想做点什么')
  })
})
