export interface VoiceboxTtsRequest {
  profile_id: string
  text: string
  language: string
  engine: 'qwen_custom_voice'
  model_size: '1.7B' | '0.6B'
  instruct: string
  normalize: true
  max_chunk_chars: number
  crossfade_ms: number
}

export interface VoiceboxTtsOptions {
  defaultProfileId?: string
  defaultLanguage?: string
  modelSize?: '1.7B' | '0.6B'
  instruct?: string
}

function isChinese(text: string) {
  return /[\u3400-\u9fff]/u.test(text)
}

/**
 * Translate the OpenAI-style request produced by @xsai/generate-speech into
 * Voicebox's local `/generate/stream` contract. Voicebox's Qwen CustomVoice
 * engine is used here because it includes Chinese male presets and accepts a
 * delivery instruction for a lively, friendly cartoon tone.
 */
export function buildVoiceboxTtsBody(rawBody: string | undefined, options: VoiceboxTtsOptions = {}): VoiceboxTtsRequest {
  let parsed: Record<string, unknown> = {}
  if (typeof rawBody === 'string' && rawBody.length > 0) {
    try {
      parsed = JSON.parse(rawBody) as Record<string, unknown>
    }
    catch {
      parsed = {}
    }
  }

  const text = typeof parsed.text === 'string'
    ? parsed.text
    : (typeof parsed.input === 'string' ? parsed.input : '')
  const profileId = typeof parsed.voice === 'string' && parsed.voice.trim()
    ? parsed.voice.trim()
    : (options.defaultProfileId ?? '')
  const language = options.defaultLanguage || (isChinese(text) ? 'zh' : 'en')

  return {
    profile_id: profileId,
    text,
    language,
    engine: 'qwen_custom_voice',
    model_size: options.modelSize ?? '1.7B',
    instruct: options.instruct ?? '温暖、活泼、亲切，带一点可爱的卡通感，语速自然，像宜小智在和用户面对面交流。',
    normalize: true,
    max_chunk_chars: 800,
    crossfade_ms: 50,
  }
}
