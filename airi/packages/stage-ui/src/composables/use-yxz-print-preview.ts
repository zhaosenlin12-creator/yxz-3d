const TRAILING_SLASH_RE = /\/$/
const HTTP_URL_RE = /^https?:\/\//i
const DASH_RE = /-/g
/** Addresses that mean "this computer" - they mean something else to a guest. */
const LOOPBACK_HOST_RE = /^(127\.0\.0\.1|localhost|::1|\[::1\])$/i

export interface YXZPreviewRequest {
  prompt: string
  n?: number
  prefer?: 'aixj' | 'minimax' | 'jojo' | 'local'
  sessionId?: string
  signal?: AbortSignal
}

export interface YXZPreviewItem {
  index: number
  caption?: string
  b64?: string
  path?: string
  source?: string
}

export interface YXZPreviewResponse {
  sessionId: string
  prompt: string
  source?: string
  previews: YXZPreviewItem[]
}

export interface YXZModelRequest {
  sessionId: string
  imageIndex: number
  customImage?: string
  signal?: AbortSignal
  onProgress?: (progress: YXZModelProgress) => void
}

export interface YXZModelProgress {
  percent: number
  message: string
  step?: string
  /** User-facing phase of the build; drives the progress checklist. */
  stage?: YXZBuildStage
}

/**
 * The phases a 3D build goes through, in the order the visitor sees them.
 *
 * The backend reports coarse engine steps; the UI only ever shows these
 * friendly phases so the visitor never reads engine names or queue chatter.
 */
export type YXZBuildStage = 'queued' | 'geometry' | 'texturing' | 'optimizing' | 'done' | 'failed'

export const YXZ_BUILD_STAGES: Array<{ id: YXZBuildStage, label: string, hint: string }> = [
  { id: 'queued', label: '准备中', hint: '已经收到你的方案，马上开工' },
  { id: 'geometry', label: '生成立体结构', hint: '把设计稿变成可以打印的立体模型' },
  { id: 'texturing', label: '上色与细节', hint: '还原你定下来的颜色和材质' },
  { id: 'optimizing', label: '打印优化', hint: '整理模型，让它可以直接打印' },
  { id: 'done', label: '完成', hint: '模型做好啦，可以预览和下载' },
]

const STAGE_BY_STEP: Array<[RegExp, YXZBuildStage]> = [
  [/^(fail|error)/i, 'failed'],
  [/^(done|complete|finished|success)/i, 'done'],
  [/^(start|queued|submit|warmup|upload|preprocess|previews)/i, 'queued'],
  [/(paint|texture|texturing|color|pbr|uv|material)/i, 'texturing'],
  [/(clean|optimi|postprocess|base|export|stl|slicer|scal|orient|centr)/i, 'optimizing'],
  [/(hunyuan|tripo|build|generat|geometry|sample|decimate|mesh|layer|reconstruct|view)/i, 'geometry'],
]

/** Map a backend step (and its percent) onto the visitor-facing phase. */
export function resolveYXZBuildStage(step?: string, percent = 0): YXZBuildStage {
  const raw = (step ?? '').trim()
  if (raw) {
    for (const [pattern, stage] of STAGE_BY_STEP) {
      if (pattern.test(raw))
        return stage
    }
  }
  if (percent >= 100)
    return 'done'
  if (percent <= 0)
    return 'queued'
  return 'geometry'
}

/** Elapsed time in a compact, human friendly form (e.g. "1 分 08 秒"). */
export function formatYXZElapsed(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes <= 0)
    return `${seconds} 秒`
  return `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒`
}

export interface YXZModelResponse {
  sessionId: string
  modelUrl: string
  stlUrl: string
  glbUrl: string
  engine?: string
}

export interface YXZLocalSoftware {
  id: string
  name: string
  kind: '3d-print' | '3d-edit' | 'laser' | string
  available: boolean
  path?: string | null
  formats: string[]
}

export interface YXZLaserCardRequest {
  /** Laser session id; re-using it overwrites the previous card. */
  sessionId?: string
  /** Preview session that owns the visitor's artwork (their model preview). */
  artworkSessionId?: string
  artworkImageIndex?: number
  name?: string
  title?: string
  unit?: string
  contact?: string
  slogan?: string
  theme?: string
  accent?: string
  note?: string
  backTemplate?: string
  /** AI-painted artwork used as the printed front face of the card. */
  frontTemplate?: string
  backCaption?: string
  /** The activity theme, typeset big in the middle of the back face. */
  backTitle?: string
  /** The quiet line under the theme. */
  backSubtitle?: string
  /** Aborts the request when the surrounding chat turn is cancelled. */
  signal?: AbortSignal
}

export interface YXZLaserCardResponse {
  sessionId: string
  svgUrl: string
  pngUrl: string
  frontUrl: string
  backUrl: string
  sizeMm: { width: number, height: number }
  backTemplate: string
  frontTemplate: string
  hasArtwork: boolean
  hasFrontArt: boolean
  message: string
}

/**
 * How long the whole preview call may take, retries included.
 *
 * The backend already falls back between image providers on its own, so a
 * single attempt can legitimately burn 90s + 90s (one provider plus one
 * retry) before it gives up.  The old 180s ceiling sat exactly on that
 * worst case, which meant every slow request ended in "预览生成超时" and
 * took the chat turn down with it.  300s leaves room for a second attempt
 * while still bounding the wait.
 */
export const YXZ_PREVIEW_TIMEOUT_MS = 300_000
export const YXZ_MODEL_TIMEOUT_MS = 10 * 60_000
export const YXZ_LASER_CARD_TIMEOUT_MS = 120_000

export function getYXZPrintApiBase() {
  const configured = (import.meta.env.VITE_CARTOON_PRINT_API || 'http://127.0.0.1:8000').replace(TRAILING_SLASH_RE, '')
  // 局域网里别的电脑打开这个页面时，配置里的 127.0.0.1 指的是访问者自己
  // 那台电脑：对话走 runtime 通道还能通，3D 生成和预览走这个地址必然失败。
  // 前端已经把 /api 代理到本机的宜小智后端，所以这里改用同源地址，
  // 只要能打开网页就能生成和预览。
  if (typeof window !== 'undefined' && window.location.hostname && !LOOPBACK_HOST_RE.test(window.location.hostname)) {
    try {
      if (LOOPBACK_HOST_RE.test(new URL(configured).hostname))
        return ''
    }
    catch {
      // Not a plain URL - keep the configured value.
    }
  }
  return configured
}

export function buildYXZPreviewPrompt(description: string, options: string[] = []) {
  const normalized = description.trim()
  const constraints = options.map(option => option.trim()).filter(Boolean)
  if (!constraints.length)
    return normalized

  return `${normalized}\n\n设计约束：${constraints.join('、')}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function parsePreviewItem(value: unknown, fallbackIndex: number): YXZPreviewItem | null {
  if (!isRecord(value))
    return null

  const index = typeof value.index === 'number' ? value.index : fallbackIndex
  const b64 = typeof value.b64 === 'string' ? value.b64 : undefined
  const path = typeof value.path === 'string' ? value.path : undefined
  if (!b64 && !path)
    return null

  return {
    index,
    b64,
    path,
    caption: typeof value.caption === 'string' ? value.caption : undefined,
    source: typeof value.source === 'string' ? value.source : undefined,
  }
}

export function previewImageSrc(item: YXZPreviewItem, baseUrl = getYXZPrintApiBase()) {
  if (item.b64)
    return item.b64.startsWith('data:') ? item.b64 : `data:image/png;base64,${item.b64}`
  if (!item.path)
    return ''
  if (HTTP_URL_RE.test(item.path))
    return item.path
  return `${baseUrl}${item.path.startsWith('/') ? item.path : `/${item.path}`}`
}

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal?.aborted) {
      resolve()
      return
    }

    const timer = setTimeout(done, ms)
    signal?.addEventListener('abort', done, { once: true })

    function done() {
      clearTimeout(timer)
      signal?.removeEventListener('abort', done)
      resolve()
    }
  })
}

function createRequestSignal(externalSignal: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const abort = () => controller.abort()
  externalSignal?.addEventListener('abort', abort, { once: true })
  if (externalSignal?.aborted)
    controller.abort()

  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    dispose: () => {
      clearTimeout(timer)
      externalSignal?.removeEventListener('abort', abort)
    },
  }
}

function absolutePrintApiUrl(path: string, baseUrl = getYXZPrintApiBase()) {
  if (HTTP_URL_RE.test(path))
    return path
  return `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
}

/**
 * Turn a model path into a URL the browser can actually fetch.
 *
 * The 3D preview page is served by the frontend, but the model files live
 * on the 宜小智 backend. A relative path such as `/api/presets/.../model.glb`
 * would therefore be resolved against the frontend origin and answer with
 * the app's own HTML page, which the GLTF loader cannot parse.
 */
export function resolveYXZModelUrl(path: string, baseUrl = getYXZPrintApiBase()) {
  const value = (path || '').trim()
  if (!value)
    return ''
  return absolutePrintApiUrl(value, baseUrl)
}

export interface YXZModelPart {
  index: number
  name: string
  glb_url: string
  stl_url: string
  faces: number
  extents_mm: number[]
  volume_mm3: number
}

export interface YXZModelPartsResponse {
  sessionId: string
  count: number
  parts: YXZModelPart[]
}

/**
 * Split a finished model into its separate bodies.
 *
 * The web workbench can animate the bodies apart, but printing them
 * separately needs one file per body - that is what the backend writes
 * here.
 */
export async function listYXZModelParts(
  sessionId: string,
  fetcher: typeof fetch = fetch,
): Promise<YXZModelPartsResponse> {
  const response = await fetcher(
    `${getYXZPrintApiBase()}/api/sessions/${encodeURIComponent(sessionId)}/parts`,
  )
  if (!response.ok)
    throw new Error(`零件拆分失败（HTTP ${response.status}）`)
  const raw: unknown = await response.json()
  if (!isRecord(raw) || !Array.isArray(raw.parts))
    return { sessionId, count: 0, parts: [] }
  const parts = raw.parts.filter((item): item is YXZModelPart => isRecord(item))
  return {
    sessionId: typeof raw.sessionId === 'string' ? raw.sessionId : sessionId,
    count: typeof raw.count === 'number' ? raw.count : parts.length,
    parts,
  }
}

export function yxzPreviewPageUrl(modelUrl: string, sessionId?: string) {
  if (typeof window === 'undefined')
    return modelUrl
  const url = new URL('/yxz-preview', window.location.origin)
  url.searchParams.set('model', modelUrl)
  // The session id lets the preview page hand the finished model straight
  // to the slicer on this machine -- without it the page can only show
  // the model and offer a download.
  if (sessionId)
    url.searchParams.set('sid', sessionId)
  return url.toString()
}

export async function detectYXZLocalSoftware(fetcher: typeof fetch = fetch): Promise<YXZLocalSoftware[]> {
  const response = await fetcher(`${getYXZPrintApiBase()}/api/software/detect`)
  if (!response.ok)
    throw new Error(`本机软件检测失败（HTTP ${response.status}）`)
  const raw: unknown = await response.json()
  if (!isRecord(raw) || !Array.isArray(raw.tools))
    return []
  return raw.tools.filter((item): item is YXZLocalSoftware => {
    if (!isRecord(item))
      return false
    return typeof item.id === 'string' && typeof item.name === 'string' && typeof item.available === 'boolean' && Array.isArray(item.formats)
  }).map(item => ({
    id: item.id,
    name: item.name,
    kind: typeof item.kind === 'string' ? item.kind : '3d-edit',
    available: item.available,
    path: typeof item.path === 'string' ? item.path : null,
    formats: item.formats.filter((format): format is string => typeof format === 'string'),
  }))
}

export async function openYXZExportInSoftware(request: { softwareId: string, sessionId?: string, format?: string, path?: string }, fetcher: typeof fetch = fetch) {
  const response = await fetcher(`${getYXZPrintApiBase()}/api/software/open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      software_id: request.softwareId,
      session_id: request.sessionId ?? '',
      fmt: request.format ?? 'stl',
      ...(request.path ? { path: request.path } : {}),
    }),
  })
  const raw: unknown = await response.json().catch(() => undefined)
  if (!response.ok)
    throw new Error(isRecord(raw) && typeof raw.detail === 'string' ? raw.detail : `打开软件失败（HTTP ${response.status}）`)
  return raw
}

export interface YXZLaserTemplate {
  id: string
  name: string
  url: string
  /** The back face rendered with the activity theme, for the picker. */
  previewUrl?: string
  sizeMm: { width: number, height: number }
  generated?: boolean
  /** Which face the artwork belongs on. */
  side?: 'back' | 'front'
}

/** List the card back templates (the packaged one plus everything the AI made). */
export async function listYXZLaserTemplates(fetcher: typeof fetch = fetch): Promise<YXZLaserTemplate[]> {
  const response = await fetcher(`${getYXZPrintApiBase()}/api/laser/templates`)
  if (!response.ok)
    throw new Error(`背景模板读取失败（HTTP ${response.status}）`)
  const raw: unknown = await response.json()
  if (!isRecord(raw) || !Array.isArray(raw.templates))
    return []
  return raw.templates.filter((item): item is Record<string, unknown> => isRecord(item)).map((item): YXZLaserTemplate => {
    const size = isRecord(item.size_mm) ? item.size_mm : {}
    return {
      id: typeof item.id === 'string' ? item.id : '',
      name: typeof item.name === 'string' ? item.name : '',
      url: typeof item.url === 'string' ? item.url : '',
      previewUrl: typeof item.preview_url === 'string' ? item.preview_url : undefined,
      sizeMm: {
        width: typeof size.width === 'number' ? size.width : 100,
        height: typeof size.height === 'number' ? size.height : 56.25,
      },
      generated: item.generated === true,
      side: item.side === 'front' ? 'front' : 'back',
    }
  }).filter(item => item.id)
}

/**
 * Ask the image service for a card back background.
 *
 * The visitor describes the look they want, the backend paints it and stores
 * it as a regular back template, so the cutting flow stays the same.
 */
export async function createYXZLaserBackground(description: string, side: 'back' | 'front' = 'back', fetcher: typeof fetch = fetch): Promise<YXZLaserTemplate> {
  const prompt = (description || '').trim()
  if (!prompt)
    throw new Error('请先描述你想要的背景')
  const response = await fetcher(`${getYXZPrintApiBase()}/api/laser/background`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description: prompt, side }),
  })
  const raw: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const detail = isRecord(raw) && typeof raw.detail === 'string' ? raw.detail : ''
    throw new Error(detail || `背景生成失败（HTTP ${response.status}）`)
  }
  if (!isRecord(raw) || typeof raw.id !== 'string')
    throw new Error('背景服务返回的数据格式无法识别')
  const size = isRecord(raw.size_mm) ? raw.size_mm : {}
  return {
    id: raw.id,
    name: typeof raw.name === 'string' ? raw.name : '我的背景',
    url: typeof raw.url === 'string' ? raw.url : '',
    sizeMm: {
      width: typeof size.width === 'number' ? size.width : 100,
      height: typeof size.height === 'number' ? size.height : 56.25,
    },
    generated: true,
    side,
  }
}

/**
 * Render the laser-cut card.
 *
 * The card is the last step of the 创作 -> 3D -> 切割 chain: its back is the
 * fixed activity artwork and its front carries the visitor's own model
 * preview, so the physical card is exactly what they designed.
 */
export async function createYXZLaserCard(request: YXZLaserCardRequest, fetcher: typeof fetch = fetch): Promise<YXZLaserCardResponse> {
  const artworkSessionId = (request.artworkSessionId ?? '').trim()
  const payload = {
    name: request.name ?? '',
    title: request.title ?? '',
    unit: request.unit ?? '',
    contact: request.contact ?? '',
    slogan: request.slogan || '数理创未来 智慧启新程',
    theme: request.theme || '#0B5FA8',
    accent: request.accent || '#F5A623',
    bg_style: 'gradient',
    back_template: request.backTemplate || 'activity_yichang',
    front_template: request.frontTemplate || '',
    back_caption: request.backCaption || '宜昌市第四届中小学生数理文化活动',
    back_title: request.backTitle || '宜昌市第四届中小学生数理文化活动',
    back_subtitle: request.backSubtitle || '宜昌 · 数理 · 文化 · 科技',
    note: request.note ?? '',
    ...(request.sessionId ? { session_id: request.sessionId } : {}),
    ...(artworkSessionId
      ? { artwork_session_id: artworkSessionId, artwork_image_index: request.artworkImageIndex ?? 0 }
      : {}),
  }

  // NOTICE: this call runs inside a chat tool.  Without a deadline a backend
  // that never answers wedges the whole turn: the assistant keeps showing
  // "正在思考" and every later message queues up behind the stuck turn.
  const linked = createRequestSignal(request.signal, YXZ_LASER_CARD_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetcher(`${getYXZPrintApiBase()}/api/laser_card`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: linked.signal,
    })
  }
  catch (error) {
    if (linked.timedOut())
      throw new Error('激光切割卡片生成超过 2 分钟仍未完成，请稍后重试')
    throw error
  }
  finally {
    linked.dispose()
  }

  const raw: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const detail = isRecord(raw) && typeof raw.detail === 'string' ? raw.detail : ''
    throw new Error(detail || `激光切割卡片生成失败（HTTP ${response.status}）`)
  }
  if (!isRecord(raw) || typeof raw.session_id !== 'string')
    throw new Error('激光切割卡片服务返回的数据格式无法识别')

  const size = isRecord(raw.size_mm) ? raw.size_mm : {}
  return {
    sessionId: raw.session_id,
    svgUrl: absolutePrintApiUrl(String(raw.svg_url ?? '')),
    pngUrl: absolutePrintApiUrl(String(raw.png_url ?? '')),
    frontUrl: absolutePrintApiUrl(String(raw.front_url ?? '')),
    backUrl: absolutePrintApiUrl(String(raw.back_url ?? '')),
    sizeMm: {
      width: typeof size.width === 'number' ? size.width : 100,
      height: typeof size.height === 'number' ? size.height : 56.25,
    },
    backTemplate: typeof raw.back_template === 'string' ? raw.back_template : 'activity_stage',
    frontTemplate: typeof raw.front_template === 'string' ? raw.front_template : '',
    hasFrontArt: raw.has_front_art === true,
    hasArtwork: raw.has_artwork === true,
    message: typeof raw.message === 'string' ? raw.message : '卡片已生成',
  }
}

/** Hand the cut SVG to the installed laser software (xTool / LightBurn). */
export async function openYXZLaserCardInSoftware(softwareId: string, sessionId: string, fetcher: typeof fetch = fetch) {
  const response = await fetcher(`${getYXZPrintApiBase()}/api/software/open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId, session_id: sessionId, fmt: 'svg' }),
  })
  const raw: unknown = await response.json().catch(() => undefined)
  if (!response.ok)
    throw new Error(isRecord(raw) && typeof raw.detail === 'string' ? raw.detail : `打开软件失败（HTTP ${response.status}）`)
  return raw
}

async function pollYXZModelProgress(sessionId: string, signal: AbortSignal, onProgress?: (progress: YXZModelProgress) => void, fetcher: typeof fetch = fetch, since = 0) {
  while (!signal.aborted) {
    try {
      const response = await fetcher(`${getYXZPrintApiBase()}/api/progress/${encodeURIComponent(sessionId)}?since=${since}`, { signal })
      if (response.ok) {
        const raw: unknown = await response.json()
        if (isRecord(raw)) {
          const events = Array.isArray(raw.events) ? raw.events : []
          for (const event of events) {
            if (!isRecord(event))
              continue
            const timestamp = typeof event.ts === 'number' ? event.ts : since
            since = Math.max(since, timestamp)
            onProgress?.({
              percent: typeof event.percent === 'number' ? event.percent : 0,
              message: typeof event.message === 'string' ? event.message : '正在生成 3D 模型…',
              step: typeof event.step === 'string' ? event.step : undefined,
              stage: typeof event.stage === 'string'
                ? event.stage as YXZBuildStage
                : resolveYXZBuildStage(
                    typeof event.step === 'string' ? event.step : undefined,
                    typeof event.percent === 'number' ? event.percent : 0,
                  ),
            })
          }
        }
      }
    }
    catch (error) {
      if ((error as Error)?.name === 'AbortError')
        return
    }
    if (signal.aborted)
      return
    await sleep(1200, signal)
  }
}

/**
 * Highest timestamp the server already knows about for this session.
 *
 * A build must not replay the events of the previous run (nor the image
 * generation phase that ran before it), otherwise the card briefly shows
 * finished / preview chatter that has nothing to do with this job.
 */
/**
 * A failure where the request never reached the 3D engine -- the backend
 * was restarting, or the connection was cut.  These are worth a retry
 * once the backend is back; a rejected model is not.
 */
class ModelTransportError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ModelTransportError'
  }
}

async function fetchLatestProgressTs(sessionId: string, fetcher: typeof fetch): Promise<number> {
  try {
    const response = await fetcher(`${getYXZPrintApiBase()}/api/progress/${encodeURIComponent(sessionId)}?since=9999999999999`)
    if (!response.ok)
      return 0
    const raw: unknown = await response.json().catch(() => undefined)
    if (!isRecord(raw))
      return 0
    const latest = raw.latest
    return isRecord(latest) && typeof latest.ts === 'number' ? latest.ts : 0
  }
  catch {
    return 0
  }
}

export async function createYXZCartoonModel(request: YXZModelRequest, fetcher: typeof fetch = fetch): Promise<YXZModelResponse> {
  if (!request.sessionId)
    throw new Error('缺少预览会话，无法生成 3D 模型')

  const linked = createRequestSignal(request.signal, YXZ_MODEL_TIMEOUT_MS)
  const progressController = new AbortController()
  const onAbort = () => progressController.abort()
  linked.signal.addEventListener('abort', onAbort, { once: true })
  const baseline = await fetchLatestProgressTs(request.sessionId, fetcher)
  const progressTask = pollYXZModelProgress(request.sessionId, progressController.signal, request.onProgress, fetcher, baseline)

  // Quality-first engine chain: Tripo3D cloud PBR (primary) ->
  // Tencent Cloud Hunyuan3D 专业版 (second, auto-switch when Tripo unreachable) ->
  // local TripoSR reconstruction (painted from the front view) -> cartoon relief.
  // Local Hunyuan3D-2 stays out of the automatic chain (slow + unpainted).
  const engines: Array<{ endpoint: string, label: string, body: Record<string, unknown> }> = [
    {
      endpoint: '/api/3d_tripo',
      label: 'Tripo3D 高清',
      body: { target_height_mm: 70, model_version: 'v3.1-20260211', texture_quality: 'detailed' },
    },
    {
      endpoint: '/api/3d_hycloud',
      label: '混元3D 云端',
      body: { target_height_mm: 70, model: '3.1', enable_pbr: true, face_count: 500000 },
    },
    {
      endpoint: '/api/3d_v2',
      label: '本地彩色 3D',
      body: { views: 1 },
    },
    {
      endpoint: '/api/3d_cartoon',
      label: 'TripoSR 浮雕',
      body: { layers: 6, layer_step_mm: 4, base_mm: 2, target_side: 384 },
    },
  ]

  let lastError: Error | null = null
  try {
    for (let i = 0; i < engines.length; i++) {
      const engine = engines[i]
      // A plain attempt plus one retry that only fires when the transport
      // broke.  The retry repeats the SAME engine: the provider never
      // failed, the connection to our own backend did.
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          request.onProgress?.({
            percent: 2,
            message: i === 0 ? '已收到你的方案，马上开始制作…' : '生成通道暂时不稳定，正在自动换一条继续…',
            step: 'building',
            stage: 'queued',
          })
          let response: Response
          try {
            response = await fetcher(`${getYXZPrintApiBase()}${engine.endpoint}`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                session_id: request.sessionId,
                image_index: request.imageIndex,
                ...(request.customImage ? { custom_image: request.customImage } : {}),
                ...engine.body,
              }),
              signal: linked.signal,
            })
          }
          catch (error) {
            throw new ModelTransportError(error instanceof Error ? error.message : '网络中断')
          }
          if (!response.ok) {
            let detail = ''
            try {
              const errRaw: unknown = await response.json()
              if (isRecord(errRaw)) {
                const d = errRaw.detail
                detail = typeof d === 'string' ? d : isRecord(d) && typeof d.error === 'string' ? d.error : ''
              }
            }
            catch { /* ignore */ }
            const message = `3D 生成服务暂时不可用（HTTP ${response.status}）${detail ? `：${detail}` : ''}`
            if ([502, 503, 504].includes(response.status))
              throw new ModelTransportError(message)
            throw new Error(message)
          }

          const raw: unknown = await response.json()
          if (!isRecord(raw) || typeof raw.session_id !== 'string' || typeof raw.model_url !== 'string')
            throw new Error('3D 生成服务返回的数据格式无法识别')

          request.onProgress?.({ percent: 100, message: '3D 模型已经做好啦，可以预览和下载了', step: 'done', stage: 'done' })
          return {
            sessionId: raw.session_id,
            modelUrl: absolutePrintApiUrl(raw.model_url),
            glbUrl: absolutePrintApiUrl(`/api/export/${raw.session_id}/glb`),
            stlUrl: absolutePrintApiUrl(`/api/export/${raw.session_id}/stl`),
            engine: typeof raw.engine === 'string' ? raw.engine : engine.label,
          }
        }
        catch (error) {
          if (linked.timedOut()) {
            request.onProgress?.({ percent: 0, message: '3D 生成超过 10 分钟仍未完成，请稍后重试', step: 'failed', stage: 'failed' })
            throw new Error('3D 生成超过 10 分钟仍未完成，请稍后重试')
          }
          // The caller cancelled the turn (the chat send recovery aborts a
          // stalled turn). Stop the engine chain here: trying the next engine
          // would keep the request alive and keep the chat queued behind it.
          if (linked.signal.aborted) {
            throw new Error('3D 生成已取消')
          }
          lastError = error instanceof Error ? error : new Error(String(error))

          if (error instanceof ModelTransportError && attempt === 0) {
            request.onProgress?.({ percent: 8, message: '生成服务正在重启，稍等一下马上继续…', step: 'building', stage: 'queued' })
            const back = await waitForYXZBackend(yxzBackendRecovery.waitMs, fetcher, linked.signal)
            if (back && !linked.signal.aborted)
              continue
          }

          request.onProgress?.({ percent: 5, message: '这一条生成通道没能完成，正在换一条继续…', step: 'building', stage: 'geometry' })
          break
        }
      }
    }
  }
  finally {
    progressController.abort()
    linked.signal.removeEventListener('abort', onAbort)
    linked.dispose()
    await progressTask.catch(() => undefined)
  }

  request.onProgress?.({ percent: 0, message: lastError?.message ?? '3D 生成失败，请重试', step: 'failed', stage: 'failed' })
  throw lastError ?? new Error('3D 生成失败，请重试')
}

/**
 * The image providers the backend knows about, in the order it prefers them.
 * When one call comes back empty we try the next one instead of giving the
 * visitor an error screen -- a single flaky provider should not end the
 * guided flow.
 */
const YXZ_PREVIEW_PROVIDERS: Array<NonNullable<YXZPreviewRequest['prefer']>> = ['aixj', 'minimax', 'jojo']

/** A failure that is worth retrying with another provider. */
class PreviewTransportError extends Error {
  /**
   * True when the backend itself looks unreachable -- it was restarting
   * after a crash, or the connection was cut.  That is worth waiting out;
   * a plain HTTP error is not.
   */
  readonly restartLikely: boolean

  constructor(message: string, restartLikely = false) {
    super(message)
    this.name = 'PreviewTransportError'
    this.restartLikely = restartLikely
  }
}

/**
 * Wait for the backend to answer again.
 *
 * The supervisor restarts the backend within seconds when it dies, but a
 * request that was in flight at that moment is already lost.  Waiting for
 * the backend to come back and then repeating the request is the
 * difference between "the visitor sees an error screen" and "the visitor
 * never notices".
 */
export const yxzBackendRecovery = {
  /** How long to wait for the backend to answer /api/ping again. */
  waitMs: 30_000,
  /** Pause between two pings. */
  pollMs: 1_000,
}

export async function waitForYXZBackend(
  timeoutMs = yxzBackendRecovery.waitMs,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
) {
  const deadline = Date.now() + Math.max(0, timeoutMs)
  while (Date.now() < deadline) {
    if (signal?.aborted)
      return false
    try {
      const response = await fetcher(`${getYXZPrintApiBase()}/api/ping`, { cache: 'no-store' })
      if (response.ok)
        return true
    }
    catch {
      // Not up yet.
    }
    await sleep(yxzBackendRecovery.pollMs, signal)
  }
  return false
}

async function requestPreviewOnce(
  prompt: string,
  prefer: NonNullable<YXZPreviewRequest['prefer']>,
  n: number,
  sessionId: string,
  timeoutMs: number,
  externalSignal: AbortSignal | undefined,
  fetcher: typeof fetch,
): Promise<YXZPreviewResponse> {
  const linked = createRequestSignal(externalSignal, Math.max(5_000, timeoutMs))
  let response: Response
  try {
    response = await fetcher(`${getYXZPrintApiBase()}/api/previews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        n,
        prefer,
        session_id: sessionId,
      }),
      signal: linked.signal,
    })
  }
  catch (error) {
    if (linked.timedOut())
      throw new PreviewTransportError('出图服务这次响应太慢了', true)
    throw new PreviewTransportError(error instanceof Error ? error.message : '网络中断', true)
  }
  finally {
    linked.dispose()
  }

  if (!response.ok) {
    // A 5xx from our own backend means the provider chain is already
    // exhausted -- walking it again from here would just triple the wait.
    // Only a gateway hiccup is worth a second try.
    if ([502, 503, 504].includes(response.status))
      throw new PreviewTransportError(`出图服务暂时不可用（HTTP ${response.status}）`, true)
    throw new Error(`出图服务暂时不可用（HTTP ${response.status}）`)
  }

  const raw: unknown = await response.json()
  if (!isRecord(raw) || typeof raw.session_id !== 'string' || !Array.isArray(raw.previews))
    throw new Error('出图服务返回的数据格式无法识别')

  const previews = raw.previews
    .map((item, index) => parsePreviewItem(item, index))
    .filter((item): item is YXZPreviewItem => item !== null)
  if (!previews.length)
    throw new Error('出图服务没有返回可展示的图片')

  return {
    sessionId: raw.session_id,
    prompt: typeof raw.prompt === 'string' ? raw.prompt : prompt,
    source: typeof raw.source === 'string' ? raw.source : undefined,
    previews,
  }
}

export async function createYXZPreview(request: YXZPreviewRequest, fetcher: typeof fetch = fetch): Promise<YXZPreviewResponse> {
  const prompt = request.prompt.trim()
  if (!prompt)
    throw new Error('请输入想要制作的产品描述')

  const n = Math.min(Math.max(request.n ?? 4, 1), 4)
  const prefer = request.prefer ?? 'aixj'
  const sessionId = request.sessionId ?? crypto.randomUUID().replace(DASH_RE, '').slice(0, 12)
  const deadline = Date.now() + YXZ_PREVIEW_TIMEOUT_MS

  // Try the preferred provider first, then the next one in line.  Each
  // attempt only gets whatever is left of the budget, so the total wait
  // stays bounded no matter how many providers we walk through.
  const candidates = [prefer, ...YXZ_PREVIEW_PROVIDERS.filter(provider => provider !== prefer)]
  let lastError: unknown

  for (const [index, candidate] of candidates.entries()) {
    const remaining = deadline - Date.now()
    if (remaining <= 5_000)
      break

    // Only the first two candidates get a real shot -- beyond that the
    // budget is already spent and we would just be adding latency.
    if (index >= 2)
      break

    try {
      return await requestPreviewOnce(
        prompt,
        candidate,
        n,
        sessionId,
        remaining,
        request.signal,
        fetcher,
      )
    }
    catch (error) {
      if (request.signal?.aborted)
        throw error
      lastError = error
      // The backend already walked its own provider chain; if it came back
      // with a clean "everything failed" answer, another attempt through a
      // different provider would repeat the same dead ends.
      if (!(error instanceof PreviewTransportError))
        break

      // The transport broke, not the provider: the backend was restarting
      // after a crash or the connection was cut mid-flight.  Waiting for it
      // to come back and repeating the very same request is what turns
      // "the visitor sees an error screen" into "the visitor never
      // noticed".  Only worth it while there is budget left.
      if (error.restartLikely) {
        const waitBudget = Math.min(yxzBackendRecovery.waitMs, deadline - Date.now())
        if (waitBudget > 3_000) {
          const back = await waitForYXZBackend(waitBudget, fetcher, request.signal)
          const retryBudget = deadline - Date.now()
          if (back && retryBudget > 5_000) {
            try {
              return await requestPreviewOnce(
                prompt,
                candidate,
                n,
                sessionId,
                retryBudget,
                request.signal,
                fetcher,
              )
            }
            catch (retryError) {
              if (request.signal?.aborted)
                throw retryError
              lastError = retryError
              if (!(retryError instanceof PreviewTransportError))
                break
            }
          }
        }
      }
    }
  }

  const reason = lastError instanceof Error ? lastError.message : '出图服务暂时没有响应'
  throw new Error(`预览没能生成出来（${reason}）。你可以直接说「再试一次」，我会换一种方式重新出图。`)
}
