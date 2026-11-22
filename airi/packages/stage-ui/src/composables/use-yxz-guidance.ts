import type { YXZRequirementMemory } from './use-yxz-requirement-memory'
import type { YXZRequirementPatch } from './use-yxz-requirement-memory'

/**
 * 宜小智的创作需求采集框架。
 *
 * 展台上的观众是中小学生：他们会兴奋地把一句话说完整，也会一句话都不说。
 * 所以这里不是一张"必填表单"，而是一份**按影响力排序**的槽位表：
 *
 *   - 影响力高、缺失代价大的槽位（做什么 / 风格 / 配色）先问；
 *   - 影响小的槽位（材质 / 数量 / 精确尺寸）给默认值，不问，除非访客主动提；
 *   - 一次只问一个，并且尽量给选项——选项比开放题更容易回答。
 *
 * 这份框架有两个出口：
 *   1. `planYXZRequirementStep` 给确定性的兜底引导（面板里用）；
 *   2. `buildYXZGuidanceBlock` 把已确认的信息写进 system prompt，
 *      让模型知道"哪些已经问过了"，从而不会重复追问。
 */

export interface YXZRequirementSlot {
  /** The memory field this slot is derived from. */
  field: string
  /** Short Chinese label used in the prompt block. */
  label: string
  /** The question to put in front of the visitor. */
  question: string
  /** Closed-set answers. Offering options makes answering trivial. */
  options?: string[]
  /** What this slot changes in the finished model. */
  hint: string
  /** The value to assume when the visitor never answers. */
  fallback?: string
}

/**
 * Slot order = how much the answer changes the rendered result.
 * `subject` first (nothing can be drawn without it), the visual slots next,
 * the finishing slots last because they have sensible defaults.
 */
export const YXZ_REQUIREMENT_SLOTS: readonly YXZRequirementSlot[] = [
  {
    field: 'description',
    label: '做什么',
    question: '想做点什么？可以先说主题、角色或用途。',
    options: ['桌面摆件', '校园徽章', '收纳小物', '纪念礼物'],
    hint: '决定造型的基本轮廓',
  },
  {
    field: 'style',
    label: '风格',
    question: '你希望它更偏圆润可爱、简洁极简，还是保留更多辨识度？',
    options: ['圆润可爱', '简洁极简', '科技硬朗', '卡通夸张'],
    hint: '决定倒角、比例和表情',
  },
  {
    field: 'palette',
    label: '配色',
    question: '主要用什么颜色？确定主色就行，其他我帮你配。',
    options: ['单色', '白 + 一个撞色', '三色渐变', '原木色'],
    hint: '决定成品上色',
  },
  {
    field: 'purpose',
    label: '用途',
    question: '这个作品主要放在哪里或送给谁？我会据此调整尺寸和细节。',
    options: ['书桌陈列', '送给同学', '班级奖品', '教室摆件'],
    hint: '决定尺寸和细节密度',
  },
  {
    field: 'audience',
    label: '受众',
    question: '是给低年级、初中还是高中同学做的？',
    hint: '决定题材复杂度和文字密度',
  },
  {
    field: 'size',
    label: '尺寸',
    question: '大概想要多大？',
    options: ['掌心小（约 5 cm）', '桌面款（约 9 cm）', '展示款（15 cm 以上）'],
    hint: '决定最终放大比例',
    fallback: '桌面款（约 9 cm 高）',
  },
  {
    field: 'material',
    label: '材质',
    question: '想用哪种打印材质？',
    options: ['PLA 哑光', '亮泽彩色', '磨砂质感', '半透明'],
    hint: '只影响切片时的表面效果',
    fallback: 'PLA 单色打印',
  },
  {
    field: 'quantity',
    label: '数量',
    question: '需要制作几个？数量会影响后续打印安排。',
    hint: '影响打印排产，不影响造型',
    fallback: '1 个',
  },
] as const

function slotByField(field: string) {
  return YXZ_REQUIREMENT_SLOTS.find(slot => slot.field === field)
}

function valueOf(memory: YXZRequirementMemory | null, field: string): string {
  if (!memory)
    return ''

  switch (field) {
    case 'description':
      return memory.description ?? ''
    case 'style':
      return memory.style ?? ''
    case 'palette':
      return memory.palette ?? ''
    case 'purpose':
      return memory.purpose ?? ''
    case 'audience':
      return memory.audience ?? ''
    case 'size':
      return memory.size ?? ''
    case 'material':
      return memory.material ?? ''
    case 'quantity':
      return memory.quantity ? String(memory.quantity) : ''
    default:
      return ''
  }
}

/**
 * The slots that are still empty.
 *
 * `constraints` count as a visual signal: a visitor who says "不要文字、
 * 要圆润" has told us more about the look than an empty style field would
 * suggest, and asking them again would feel like the app was not listening.
 */
export function getYXZMissingRequirementSlots(memory: YXZRequirementMemory | null): YXZRequirementSlot[] {
  const constraints = memory?.constraints ?? []
  return YXZ_REQUIREMENT_SLOTS.filter((slot) => {
    if (slot.field === 'style' && constraints.length)
      return false
    return !valueOf(memory, slot.field)
  })
}

/**
 * Enough information to draw something the visitor recognises?
 *
 * A subject plus one *visual* signal is the bar: the style, the colours
 * or an explicit look the visitor spelled out ("不要文字", "要圆润").
 * Purpose and audience used to count as well, which made the readiness
 * check disagree with the model: "摆在书桌上" was enough for the code
 * to say "go and draw", while the model still asked for a style -- and
 * from the visitor's side that looked like the app was making things up.
 *
 * Everything else has a default and is better answered by the model in
 * one short sentence ("我先按 9cm 桌面款做") than by another question.
 */
export function isYXZRequirementReady(memory: YXZRequirementMemory | null): boolean {
  if (!memory?.description)
    return false

  const constraints = memory.constraints ?? []
  return Boolean(
    memory.style
    || memory.palette
    || constraints.length,
  )
}

/**
 * The single next question worth asking.
 *
 * Returns `null` once the requirement is ready to render -- at that point
 * the right move is to generate, not to keep interviewing.
 *
 * Readiness and the plan are deliberately the same predicate: a question
 * that the "ready" check would ignore is a question the app would still
 * ask, which is exactly the nagging the visitor remembers.
 */
export function planYXZRequirementStep(memory: YXZRequirementMemory | null): YXZRequirementSlot | null {
  if (!memory?.description)
    return YXZ_REQUIREMENT_SLOTS.find(slot => slot.field === 'description') ?? null

  // Enough to draw? Then stop asking and go render.
  if (isYXZRequirementReady(memory))
    return null

  // Nothing about the look or the context yet. The style is the single
  // most useful question: it changes the silhouette the most and a
  // student answers it in one word.
  return YXZ_REQUIREMENT_SLOTS.find(slot => slot.field === 'style') ?? null
}

/**
 * The same plan, phrased as a sentence for the visitor.
 */
export function getYXZRequirementNextQuestion(memory: YXZRequirementMemory | null): string {
  const step = planYXZRequirementStep(memory)
  if (!step) {
    if (!memory?.description)
      return YXZ_REQUIREMENT_SLOTS[0].question
    return '需求已经比较完整，可以确认预览并进入 3D 制作。'
  }

  return step.question
}

/**
 * The requirement memory rendered as a block the model can act on.
 *
 * Two halves on purpose: what is settled (never ask again) and what is
 * still open (assume the default, mention it in one line).
 */
export function buildYXZGuidanceBlock(memory: YXZRequirementMemory | null, intent?: YXZVisitorIntent): string {
  const lines: string[] = []

  if (intent) {
    lines.push(
      '【访客这句的意思】',
      YXZ_INTENT_HINTS[intent],
    )
  }

  if (!memory)
    return lines.join('\n')

  const confirmed: string[] = []
  for (const slot of YXZ_REQUIREMENT_SLOTS) {
    const value = valueOf(memory, slot.field)
    if (value)
      confirmed.push(`- ${slot.label}：${value}`)
  }

  if (memory.constraints?.length)
    confirmed.push(`- 其他要求：${memory.constraints.join('、')}`)

  if (confirmed.length)
    lines.push('【本次创作已确认的需求】', ...confirmed)

  if (confirmed.length) {
    const missing = getYXZMissingRequirementSlots(memory)
      .filter(slot => slot.fallback)
      .map(slot => `- ${slot.label}：默认${slot.fallback}`)

    if (missing.length) {
      lines.push(
        '【尚未确认，按默认处理即可】',
        ...missing,
      )
    }

    lines.push(
      '已确认的信息不要重复提问；缺失项若不影响出图就直接按默认值做，并在回复里用一句话说明。',
    )
  }

  return lines.join('\n')
}

/**
 * A one-line summary for the visitor ("白蓝配色 · 圆润 · 约 9cm").
 */
export function summarizeYXZRequirement(memory: YXZRequirementMemory | null): string {
  if (!memory)
    return ''

  const parts = [
    memory.style,
    memory.palette,
    memory.size,
    memory.material,
  ].filter(Boolean) as string[]

  return parts.join(' · ')
}

/**
 * Pull the slots out of free text.
 *
 * The model phrases a request as prose ("一个圆润可爱的白蓝配色小摆件，
 * 大概 9 厘米").  Parsing that prose here -- instead of asking the model to
 * keep a structured summary straight -- means the memory stays correct even
 * when the model forgets, and the prompt block can be rebuilt from scratch
 * after every turn.
 */
const STYLE_SIGNALS: Record<string, string> = {
  圆润: '圆润可爱',
  可爱: '圆润可爱',
  萌: '圆润可爱',
  Q版: '圆润可爱',
  极简: '简洁极简',
  简约: '简洁极简',
  简洁: '简洁极简',
  科技: '科技硬朗',
  硬朗: '科技硬朗',
  机械: '科技硬朗',
  卡通: '卡通夸张',
  夸张: '卡通夸张',
  拟人: '卡通夸张',
}

const PALETTE_SIGNALS: Record<string, string> = {
  单色: '单色',
  白: '白色',
  黑: '黑色',
  深蓝: '深蓝色',
  蓝色: '蓝色',
  浅蓝: '浅蓝色',
  红: '红色',
  粉: '粉色',
  黄: '黄色',
  金: '金色',
  银: '银色',
  绿: '绿色',
  渐变: '渐变',
  撞色: '撞色',
  原木: '原木色',
  木色: '原木色',
}

const SIZE_SIGNALS: Record<string, string> = {
  掌心: '掌心小（约 5 cm）',
  迷你: '掌心小（约 5 cm）',
  小巧: '掌心小（约 5 cm）',
  桌面: '桌面款（约 9 cm）',
  书桌: '桌面款（约 9 cm）',
  常规: '桌面款（约 9 cm）',
  展示: '展示款（15 cm 以上）',
  大号: '展示款（15 cm 以上）',
}

function matchSignal(text: string, table: Record<string, string>): string {
  for (const [needle, label] of Object.entries(table)) {
    if (text.includes(needle))
      return label
  }
  return ''
}

/**
 * Extract every slot that the free text mentions.
 *
 * Returns only the slots that were actually found, so a caller can merge
 * them into the memory without blanking out what is already known.
 */
export function extractYXZRequirementSignals(text: string): {
  style?: string
  palette?: string
  size?: string
  purpose?: string
} {
  const value = (text ?? '').trim()
  if (!value)
    return {}

  const result: { style?: string, palette?: string, size?: string, purpose?: string } = {}

  const style = matchSignal(value, STYLE_SIGNALS)
  if (style)
    result.style = style

  const palette = matchSignal(value, PALETTE_SIGNALS)
  if (palette)
    result.palette = palette

  const size = matchSignal(value, SIZE_SIGNALS)
  if (size)
    result.size = size

  if (/桌面|书桌|摆件|陈列/.test(value))
    result.purpose = result.purpose ?? '桌面陈列'
  else if (/礼物|送|纪念/.test(value))
    result.purpose = result.purpose ?? '纪念礼物'
  else if (/徽章|校徽/.test(value))
    result.purpose = result.purpose ?? '校园纪念徽章'

  return result
}

export { slotByField }

/**
 * What the visitor's own message is asking for.
 *
 * The model used to read every message as "the requirements changed, go
 * and draw something".  A visitor who typed "你???" after a failed
 * preview therefore got another long image generation and a cheerful
 * answer about a picture that was never made.  Deciding this in code --
 * where it can be tested -- keeps the assistant honest.
 */
export type YXZVisitorIntent
  = | 'regenerate'
    | 'confused'
    | 'question'
    | 'refine'
    | 'new-requirement'

/** "再出一次 / 换一批 / 重新生成" -- the same brief, drawn again. */
const YXZ_REGENERATE_RE = /再(?:出|来|试|做)一?次|再来一?张|换一?批|再看看|重新(?:生成|出图|做|来|设计)|再生成|重新来/

/** "你??? / 怎么还没好 / 不是这个" -- the visitor is unhappy or lost. */
const YXZ_CONFUSED_RE = /^[\s?？!！。.…·、,，~～]*$|你[?？]+|怎么(?:还|没|不)|什么(?:情况|意思|回事)|啥(?:情况|意思)|怎么回事|怎么这样|不是(?:这个|我要|我想|这样)|不对|错了|失败|没(?:有)?(?:出来|生成|反应|动静)|卡住|不动|听不懂/

/** The visitor is describing a product rather than talking about the app. */
const YXZ_MAKE_RE = /(?:做|制作|设计|定制|建模|打印)(?:出|个|一个|款|只|张|样|点)?|想要|我要|想做|帮我做|来一?个|生成一?个|做个|做个/

/**
 * "打印要多久" is a question about the making, not a brief.
 *
 * It has to be recognised before the make-verb rule, because "打印" is
 * one of the make verbs and the visitor would otherwise get a picture
 * instead of an answer -- the exact "答非所问" the booth visitors
 * complained about.
 */
const YXZ_ASK_DURATION_RE = /多久|多长时间|什么时候|几天|几号|多大|多重|多贵|多少钱/

/** The visitor named a subject: "我要个小熊", "帮我做个机器人". */
const YXZ_BRIEF_RE = /我要|我想|想做|我想要|帮我(?:做|来|定)|来一?个|做个|做个/

/** A change to the picture that was already made. */
const YXZ_REFINE_RE = /换(?:个|成|一下)?(?:颜色|配色|造型|风格|材料)|改成|调整|加大|缩小|大一点|小一点|加(?:个|点|上)|去掉|不要|换(?:个|成|一下)?[^，。,.\s]{1,6}色|改成[^，。,.\s]{1,6}色|要[^，。,.\s]{1,4}色|(?:深|浅|亮|暗|厚|薄|长|短|大|小)一点/

/** A plain question about the exhibition or about the making. */
const YXZ_QUESTION_RE = /[?？]\s*$|吗\s*$|呢\s*$|怎么|如何|为什么|能不能|可不可以|好不好|行不行|是不是|哪些|哪个|多少|几点|什么时候|哪里|在哪|几点钟/

/**
 * Read one visitor message.
 *
 * The order matters: a complaint ("怎么还没好") is also a question and
 * also contains "怎么", and a "make me one" request is often phrased as
 * a question ("能帮我做个摆件吗").  Both have to be recognised before the
 * generic question rule gets a chance to swallow them.
 */
export function classifyYXZVisitorIntent(text: string): YXZVisitorIntent {
  const value = (text ?? '').trim()
  if (!value)
    return 'question'

  if (YXZ_REGENERATE_RE.test(value))
    return 'regenerate'

  if (YXZ_CONFUSED_RE.test(value)) {
    // A complaint that still carries a brief is a brief: "怎么还没好，我要
    // 个小熊" has to produce the cat, not a clarification question.
    if (!/[?？]\s*$/.test(value) && value.length >= 8 && YXZ_BRIEF_RE.test(value))
      return 'new-requirement'

    return 'confused'
  }

  if (YXZ_ASK_DURATION_RE.test(value))
    return 'question'

  if (YXZ_MAKE_RE.test(value))
    return 'new-requirement'

  if (YXZ_REFINE_RE.test(value))
    return 'refine'

  if (YXZ_QUESTION_RE.test(value))
    return 'question'

  return 'new-requirement'
}

/**
 * The subject a visitor named, if the message really names one.
 *
 * Kept apart from the complaint handling on purpose: a muddle that still
 * says "我要个小熊" has to keep that subject, otherwise the visitor has
 * to repeat themselves.
 */
export function extractYXZVisitorBrief(text: string): YXZRequirementPatch {
  const value = (text ?? '').trim()
  if (!value || value.length < 6 || !YXZ_MAKE_RE.test(value))
    return {}

  return { description: value }
}

/** One line that tells the model what this message is. */
const YXZ_INTENT_HINTS: Record<YXZVisitorIntent, string> = {
  'regenerate': '访客要的是「再来一版」：沿用已经确认的需求重新出图，不要重新问需求。',
  'confused': '访客在表达困惑或不满：先用一句话回应，问清楚哪里不对劲，不要自作主张重新出图，也不要说已经出好了。',
  'question': '访客在提问：只回答这个问题，一句话讲清楚。不要调用任何出图或制作工具，不要重新出图，也不要说已经出图了。',
  'refine': '访客在提修改意见：把改动并入需求后重新出图。',
  'new-requirement': '访客在描述新需求：看下面还缺什么，只补问最关键的那一个。',
}

/**
 * What the visitor's own words add to the requirement.
 *
 * The memory used to be written by the preview tool only, so the system
 * prompt carried nothing about the visitor until a picture had already
 * been drawn -- and the model then had to guess, differently every time,
 * whether the subject was still open.
 */
export function extractYXZVisitorPatch(text: string, intent: YXZVisitorIntent): YXZRequirementPatch {
  const patch: YXZRequirementPatch = {}
  const value = (text ?? '').trim()
  if (!value)
    return patch

  // A complaint, a question or "again please" carries no new requirement.
  if (intent === 'confused' || intent === 'question' || intent === 'regenerate')
    return patch

  const signals = extractYXZRequirementSignals(value)
  if (signals.style)
    patch.style = signals.style
  if (signals.palette)
    patch.palette = signals.palette
  if (signals.size)
    patch.size = signals.size
  if (signals.purpose)
    patch.purpose = signals.purpose

  // The visitor's own hard requirements ("不要文字", "要点蓝色") are kept
  // word for word: the model needs the original phrasing, not a label.
  if (/(?:不要|别|不加|去掉|没有|不能|必须|一定|要加|加点|加上|带|换成|改成)/.test(value))
    patch.constraints = [value]

  // The subject is only taken from a sentence that really describes one.
  if (intent === 'new-requirement') {
    const brief = extractYXZVisitorBrief(value)
    if (brief.description)
      patch.description = brief.description
  }

  return patch
}

/**
 * What the visitor can see right now.
 */
export interface YXZClarificationContext {
  /** A finished preview card is on screen. */
  hasPreview: boolean
  /** A preview or a 3D model is still being generated. */
  isBuilding: boolean
  /** The subject the visitor already gave, if any. */
  description?: string
}

/**
 * The answer to a visitor who is confused or unhappy.
 *
 * This is written in code on purpose.  The model used to receive the
 * complaint, decide on its own that it should draw again, and either
 * start a long generation or fall back to "刚才这一句我没接住" -- both
 * of which cost the visitor seconds and told them nothing.  The screen
 * already knows what happened, so the reply is built from the screen.
 *
 * Two rules it must never break:
 *   - never claim a preview exists when it does not;
 *   - never start a new generation from here.
 */
export function buildYXZClarificationReply(context: YXZClarificationContext): string {
  if (context.isBuilding)
    return '还在生成中，稍等一下就好，我盯着进度。'

  if (context.hasPreview)
    return '预览已经出来了，是这一版跟你想的不一样吗？告诉我要改哪儿——造型、配色、大小都行，我马上改。'

  const description = (context.description ?? '').trim()
  if (description)
    return `我记着你要做的是「${description}」。是想再补充点细节，还是我直接出预览图给你看？`

  return '你想做点什么呀？说一句话就行，比如「一个校园纪念徽章」。'
}
