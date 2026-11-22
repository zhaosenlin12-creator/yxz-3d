import { getCurrentInstance, onUnmounted, ref } from 'vue'

import { getYXZPrintApiBase } from './use-yxz-print-preview'

export type YXZVoiceInputState = 'idle' | 'recording' | 'transcribing' | 'error'

export interface YXZVoiceInputOptions {
  /** The microphone to record from; empty means "the system default". */
  deviceId?: () => string | undefined
  /** The language hint. 宜小智 listens to Mandarin, so that is the default. */
  language?: string
  /** Called with the recognised text. */
  onText?: (text: string) => void
  /** Called when the recording or the transcription failed. */
  onError?: (message: string) => void
  /** Stop recording after this much silence (0 disables the timer). */
  silenceTimeoutMs?: number
}

export interface YXZVoiceInputResult {
  text: string
  duration: number
  elapsed: number
}

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

/** Above this level the microphone is considered to be hearing the user. */
const VOICE_LEVEL = 0.035

/**
 * How long the room has to stay quiet before the recording ends.
 *
 * The old value was 3.5s, which meant every single utterance was followed
 * by three and a half seconds of dead air before anything happened.  A
 * student who says "就这个吧" waits those 3.5s and then another three
 * seconds for the transcription.  1.5s is long enough for the pause
 * somebody takes between two clauses, and short enough that the pause
 * does not feel like the app is stuck.
 */
const DEFAULT_SILENCE_TIMEOUT_MS = 1500

/**
 * How often the running caption is refreshed while the visitor speaks.
 *
 * The quick model answers in about a second, so a caption that refreshes
 * every 1.1s keeps the screen busy without piling requests on the CPU.
 */
const CAPTION_INTERVAL_MS = 1100

/** Below this much audio there is nothing worth captioning yet. */
const CAPTION_MIN_AUDIO_MS = 900

function errorText(error: unknown): string {
  if (error instanceof Error)
    return error.message
  return String(error ?? '')
}

// The level meter runs on requestAnimationFrame, which does not exist
// outside a browser; the timer keeps the code usable in a test runner.
function nextFrame(handler: () => void): number {
  if (typeof requestAnimationFrame === 'function')
    return requestAnimationFrame(handler)
  return setTimeout(handler, 60) as unknown as number
}

function cancelFrame(id: number) {
  if (!id)
    return
  if (typeof cancelAnimationFrame === 'function')
    cancelAnimationFrame(id)
  else
    clearTimeout(id as unknown as ReturnType<typeof setTimeout>)
}

/**
 * Voice input that runs on the machine that serves 宜小智.
 *
 * The old implementation leaned on the browser's own SpeechRecognition,
 * which Chrome streams to Google's servers: one dropped packet and the
 * button stops answering.  Here the browser only records a short clip
 * with the native MediaRecorder, and the local backend transcribes it
 * with faster-whisper.  No key, no quota, no network, same result on
 * every computer in the room.
 */
export function useYXZVoiceInput(options: YXZVoiceInputOptions = {}) {
  const state = ref<YXZVoiceInputState>('idle')
  const level = ref(0)
  const elapsed = ref(0)
  const message = ref('')
  /**
   * The provisional text of what is being said right now.
   *
   * It is produced by the quick model while the visitor is still talking,
   * so the screen shows their words within about a second instead of
   * staying blank for three.  The accurate model replaces it a moment
   * later with the final answer.
 */
  const partialText = ref('')
  /** How long the current transcription has been running. */
  const transcribingFor = ref(0)

  let stream: MediaStream | null = null
  let recorder: MediaRecorder | null = null
  let chunks: BlobPart[] = []
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let frame = 0
  let startedAt = 0
  let lastVoiceAt = 0
  let heardVoice = false
  let finishing = false
  let captionTimer = 0
  let captionBusy = false
  let captionGeneration = 0
  let captionController: AbortController | null = null
  let transcriptionTimer = 0

  function supported(): boolean {
    return typeof navigator !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== 'undefined'
  }

  function fail(text: string) {
    message.value = text
    state.value = 'error'
    options.onError?.(text)
  }

  function teardown() {
    cancelFrame(frame)
    frame = 0
    clearTimeout(captionTimer)
    captionTimer = 0
    level.value = 0
    try {
      recorder?.stream.getTracks().forEach(track => track.stop())
    }
    catch {}
    try {
      stream?.getTracks().forEach(track => track.stop())
    }
    catch {}
    try {
      audioContext?.close()
    }
    catch {}
    recorder = null
    stream = null
    audioContext = null
    analyser = null
  }

  function pickMimeType(): string {
    if (typeof MediaRecorder === 'undefined')
      return ''
    for (const type of MIME_CANDIDATES) {
      try {
        if (MediaRecorder.isTypeSupported?.(type))
          return type
      }
      catch {}
    }
    return ''
  }

  function watchLevel() {
    if (!analyser)
      return
    const data = new Float32Array(analyser.fftSize)
    const tick = () => {
      if (!analyser)
        return
      analyser.getFloatTimeDomainData(data)
      let sum = 0
      for (const sample of data)
        sum += sample * sample
      const rms = Math.sqrt(sum / data.length)
      level.value = Math.min(1, rms * 4)
      elapsed.value = Math.max(0, (performance.now() - startedAt) / 1000)

      const now = performance.now()
      if (rms > VOICE_LEVEL) {
        heardVoice = true
        lastVoiceAt = now
      }
      else if (heardVoice) {
        // Long enough for a student to think about the next word, short
        // enough that the recording does not drag on after they stop.
        const silenceLimit = options.silenceTimeoutMs ?? DEFAULT_SILENCE_TIMEOUT_MS
        if (silenceLimit > 0 && now - lastVoiceAt > silenceLimit) {
          void stop()
          return
        }
      }
      frame = nextFrame(tick)
    }
    frame = nextFrame(tick)
  }

  async function start(): Promise<boolean> {
    if (state.value === 'recording')
      return true
    if (!supported()) {
      // 局域网 http:// 访问时浏览器不给 mediaDevices（不是安全上下文），
      // 这时候要说清楚真实原因，别让用户以为是浏览器不支持。
      const insecure = typeof window !== 'undefined' && window.isSecureContext === false
      fail(insecure
        ? '浏览器只在 https 或本机地址下允许录音；在局域网用 http:// 打开时不能录音，请用文字输入，或改用 https 打开本页'
        : '当前浏览器不支持录音，请用 Chrome 或 Edge 打开本页')
      return false
    }

    finishing = false
    message.value = ''
    heardVoice = false
    chunks = []

    try {
      const deviceId = options.deviceId?.()
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
    }
    catch (error) {
      const name = (error as { name?: string })?.name
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        fail('麦克风权限被拒绝了，请在浏览器地址栏左侧允许本页使用麦克风')
      }
      else if (name === 'NotFoundError') {
        fail('没有找到可用的麦克风，请检查系统的录音设备')
      }
      else {
        fail(`无法打开麦克风：${errorText(error)}`)
      }
      return false
    }

    try {
      const mimeType = pickMimeType()
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0)
          chunks.push(event.data)
      }
      recorder.start(200)
    }
    catch (error) {
      teardown()
      fail(`无法开始录音：${errorText(error)}`)
      return false
    }

    // The level meter is what tells the student that the microphone is
    // really picking their voice up.
    try {
      audioContext = new AudioContext()
      if (audioContext.state === 'suspended')
        await audioContext.resume()
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 1024
      audioContext.createMediaStreamSource(stream).connect(analyser)
      startedAt = performance.now()
      lastVoiceAt = startedAt
      watchLevel()
    }
    catch {
      analyser = null
    }

    state.value = 'recording'
    elapsed.value = 0
    partialText.value = ''
    scheduleCaption()
    return true
  }

  async function transcribe(blob: Blob, partial = false, external?: AbortSignal): Promise<YXZVoiceInputResult> {
    const base = getYXZPrintApiBase()
    const query = new URLSearchParams({ language: options.language ?? 'zh' })
    if (partial)
      query.set('partial', '1')
    const url = `${base}/api/asr/transcribe?${query.toString()}`
    const controller = new AbortController()
    external?.addEventListener('abort', () => controller.abort(), { once: true })
    const timer = setTimeout(() => controller.abort(), 120_000)
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm' },
        body: blob,
        signal: controller.signal,
      })
      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `语音服务返回 ${response.status}`)
      }
      const payload = await response.json()
      return {
        text: String(payload?.text ?? '').trim(),
        duration: Number(payload?.duration ?? 0),
        elapsed: Number(payload?.elapsed ?? 0),
      }
    }
    finally {
      clearTimeout(timer)
    }
  }

  /**
   * Ask the quick model what has been said so far.
   *
   * Only one caption request is in flight at a time, and a caption that
   * arrives after the recording ended is dropped -- by then the accurate
   * answer is on its way and the old caption would only make the text
   * flicker backwards.
   */
  async function refreshCaption() {
    if (captionBusy || state.value !== 'recording' || !chunks.length)
      return

    const recordedFor = performance.now() - startedAt
    if (recordedFor < CAPTION_MIN_AUDIO_MS)
      return

    const generation = captionGeneration
    const mimeType = recorder?.mimeType || 'audio/webm'
    const blob = new Blob(chunks, { type: mimeType })
    if (blob.size < 512)
      return

    const controller = new AbortController()
    captionController = controller
    captionBusy = true
    try {
      const result = await transcribe(blob, true, controller.signal)
      if (generation !== captionGeneration)
        return
      if (result.text)
        partialText.value = result.text
    }
    catch {
      // A caption is a nice-to-have; a failed one must never interrupt
      // the recording.
    }
    finally {
      captionBusy = false
      if (captionController === controller)
        captionController = null
    }
  }

  function scheduleCaption() {
    clearTimeout(captionTimer)
    captionTimer = setTimeout(() => {
      void refreshCaption().finally(() => {
        if (state.value === 'recording')
          scheduleCaption()
      })
    }, CAPTION_INTERVAL_MS) as unknown as number
  }

  async function stop(): Promise<string> {
    if (state.value !== 'recording' || finishing)
      return ''
    finishing = true
    // Any caption still on its way belongs to the recording that just
    // ended; letting it land would overwrite the accurate answer.
    captionGeneration += 1
    clearTimeout(captionTimer)
    captionTimer = 0
    // Abort the caption that is still in flight.  It would otherwise keep
    // the CPU busy for another second and delay the answer the visitor is
    // actually waiting for.
    captionController?.abort()
    captionController = null
    captionBusy = false

    const mimeType = recorder?.mimeType || 'audio/webm'
    try {
      if (recorder && recorder.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          recorder!.addEventListener('stop', () => resolve(), { once: true })
          recorder!.stop()
        })
      }
    }
    catch {}

    const blob = new Blob(chunks, { type: mimeType })
    teardown()

    if (blob.size < 512) {
      finishing = false
      fail('没有听到声音，请靠近麦克风再试一次')
      return ''
    }

    state.value = 'transcribing'
    transcribingFor.value = 0
    clearInterval(transcriptionTimer)
    transcriptionTimer = setInterval(() => {
      transcribingFor.value += 100
    }, 100) as unknown as number
    try {
      const result = await transcribe(blob)
      finishing = false
      clearInterval(transcriptionTimer)
      transcriptionTimer = 0
      transcribingFor.value = 0
      if (!result.text) {
        partialText.value = ''
        fail('没有听清，请再说一遍')
        return ''
      }
      state.value = 'idle'
      message.value = ''
      // The accurate answer replaces the provisional caption.
      partialText.value = ''
      options.onText?.(result.text)
      return result.text
    }
    catch (error) {
      finishing = false
      clearInterval(transcriptionTimer)
      transcriptionTimer = 0
      transcribingFor.value = 0
      partialText.value = ''
      const aborted = (error as { name?: string })?.name === 'AbortError'
      fail(aborted ? '语音识别超时了，请再说一次' : `语音识别失败：${errorText(error)}`)
      return ''
    }
  }

  function cancel() {
    finishing = true
    captionGeneration += 1
    clearTimeout(captionTimer)
    captionTimer = 0
    captionController?.abort()
    captionController = null
    captionBusy = false
    clearInterval(transcriptionTimer)
    transcriptionTimer = 0
    try {
      if (recorder && recorder.state !== 'inactive')
        recorder.stop()
    }
    catch {}
    chunks = []
    teardown()
    finishing = false
    partialText.value = ''
    transcribingFor.value = 0
    state.value = 'idle'
  }

  // The composable is also used outside a component (in a test), where
  // there is no lifecycle to hook into.
  if (getCurrentInstance())
    onUnmounted(() => cancel())

  return {
    state,
    level,
    elapsed,
    message,
    partialText,
    transcribingFor,
    supported,
    start,
    stop,
    cancel,
  }
}
