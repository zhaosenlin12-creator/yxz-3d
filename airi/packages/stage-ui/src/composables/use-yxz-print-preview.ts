const TRAILING_SLASH_RE = /\/$/
const HTTP_URL_RE = /^https?:\/\//i
const DASH_RE = /-/g

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
  backCaption?: string
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
  hasArtwork: boolean
  message: string
}

export const YXZ_PREVIEW_TIMEOUT_MS = 180_000
export const YXZ_MODEL_TIMEOUT_MS = 10 * 60_000
export const YXZ_LASER_CARD_TIMEOUT_MS = 120_000

export function getYXZPrintApiBase() {
  return (import.meta.env.VITE_CARTOON_PRINT_API || 'http://127.0.0.1:8000').replace(TRAILING_SLASH_RE, '')
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

export function yxzPreviewPageUrl(modelUrl: string) {
  if (typeof window === 'undefined')
    return modelUrl
  const url = new URL('/yxz-preview', window.location.origin)
  url.searchParams.set('model', modelUrl)
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

export async function openYXZExportInSoftware(request: { softwareId: string, sessionId: string, format?: string }, fetcher: typeof fetch = fetch) {
  const response = await fetcher(`${getYXZPrintApiBase()}/api/software/open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: request.softwareId, session_id: request.sessionId, fmt: request.format ?? 'stl' }),
  })
  const raw: unknown = await response.json().catch(() => undefined)
  if (!response.ok)
    throw new Error(isRecord(raw) && typeof raw.detail === 'string' ? raw.detail : `打开软件失败（HTTP ${response.status}）`)
  return raw
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
    back_template: request.backTemplate || 'activity_stage',
    back_caption: request.backCaption || '宜昌市第四届中小学生数理文化活动',
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

async function pollYXZModelProgress(sessionId: string, signal: AbortSignal, onProgress?: (progress: YXZModelProgress) => void, fetcher: typeof fetch = fetch) {
  let since = 0
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

export async function createYXZCartoonModel(request: YXZModelRequest, fetcher: typeof fetch = fetch): Promise<YXZModelResponse> {
  if (!request.sessionId)
    throw new Error('缺少预览会话，无法生成 3D 模型')

  const linked = createRequestSignal(request.signal, YXZ_MODEL_TIMEOUT_MS)
  const progressController = new AbortController()
  const onAbort = () => progressController.abort()
  linked.signal.addEventListener('abort', onAbort, { once: true })
  const progressTask = pollYXZModelProgress(request.sessionId, progressController.signal, request.onProgress, fetcher)

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
      try {
        request.onProgress?.({
          percent: 2,
          message: i === 0 ? '开始制作 3D 模型，请耐心等待…' : `${engine.label} 引擎不可用，正在切换备用引擎（${i + 1}/${engines.length}）…`,
          step: 'building',
        })
        const response = await fetcher(`${getYXZPrintApiBase()}${engine.endpoint}`, {
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
          throw new Error(`3D 生成服务暂时不可用（HTTP ${response.status}）${detail ? `：${detail}` : ''}`)
        }

        const raw: unknown = await response.json()
        if (!isRecord(raw) || typeof raw.session_id !== 'string' || typeof raw.model_url !== 'string')
          throw new Error('3D 生成服务返回的数据格式无法识别')

        request.onProgress?.({ percent: 100, message: `3D 模型已生成（${engine.label}）`, step: 'done' })
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
          request.onProgress?.({ percent: 0, message: '3D 生成超过 10 分钟仍未完成，请稍后重试', step: 'failed' })
          throw new Error('3D 生成超过 10 分钟仍未完成，请稍后重试')
        }
        lastError = error instanceof Error ? error : new Error(String(error))
        request.onProgress?.({ percent: 5, message: `${engine.label} 引擎失败，尝试下一个引擎…`, step: 'building' })
      }
    }
  }
  finally {
    progressController.abort()
    linked.signal.removeEventListener('abort', onAbort)
    linked.dispose()
    await progressTask.catch(() => undefined)
  }

  request.onProgress?.({ percent: 0, message: lastError?.message ?? '3D 生成失败，请重试', step: 'failed' })
  throw lastError ?? new Error('3D 生成失败，请重试')
}

export async function createYXZPreview(request: YXZPreviewRequest, fetcher: typeof fetch = fetch): Promise<YXZPreviewResponse> {
  const prompt = request.prompt.trim()
  if (!prompt)
    throw new Error('请输入想要制作的产品描述')

  const linked = createRequestSignal(request.signal, YXZ_PREVIEW_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetcher(`${getYXZPrintApiBase()}/api/previews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        n: Math.min(Math.max(request.n ?? 4, 1), 4),
        prefer: request.prefer ?? 'aixj',
        session_id: request.sessionId ?? crypto.randomUUID().replace(DASH_RE, '').slice(0, 12),
      }),
      signal: linked.signal,
    })
  }
  catch (error) {
    if (linked.timedOut())
      throw new Error('预览生成超过 2 分钟仍未完成，请稍后重试')
    throw error
  }
  finally {
    linked.dispose()
  }

  if (!response.ok)
    throw new Error(`预览服务暂时不可用（HTTP ${response.status}）`)

  const raw: unknown = await response.json()
  if (!isRecord(raw) || typeof raw.session_id !== 'string' || !Array.isArray(raw.previews))
    throw new Error('预览服务返回的数据格式无法识别')

  const previews = raw.previews
    .map((item, index) => parsePreviewItem(item, index))
    .filter((item): item is YXZPreviewItem => item !== null)
  if (!previews.length)
    throw new Error('预览服务没有返回可展示的图片')

  return {
    sessionId: raw.session_id,
    prompt: typeof raw.prompt === 'string' ? raw.prompt : prompt,
    source: typeof raw.source === 'string' ? raw.source : undefined,
    previews,
  }
}
