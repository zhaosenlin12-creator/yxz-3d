export interface MinimaxTtsRequest {
  model: string
  text: string
  voice_setting: {
    voice_id: string
    speed: number
    vol: number
    pitch: number
  }
  audio_setting: {
    sample_rate: number
    bitrate: number
    format: 'mp3' | 'wav' | 'pcm'
    channel: number
  }
  stream: false
}

export interface MinimaxTtsOptions {
  defaultVoiceId?: string
}

/**
 * Translate the OpenAI-style TTS body produced by `@xsai/generate-speech`
 * into the body shape accepted by MiniMax's `POST /v1/t2a_v2` endpoint.
 *
 * MiniMax's t2a_v2 endpoint does not understand the OpenAI `{ input, voice }`
 * shape; it requires `{ text, voice_setting.voice_id, audio_setting, model }`.
 * Sending the upstream body through unchanged causes the API to return an error
 * and the streaming TTS pipeline to silently drop the rest of the reply,
 * which is what produced the English-fallback / incomplete-playback behaviour.
 */
export function buildMinimaxTtsBody(rawBody: string | undefined, options: MinimaxTtsOptions = {}): MinimaxTtsRequest {
  const defaultVoiceId = options.defaultVoiceId ?? 'female-shaonv'

  let parsed: Record<string, any> = {}
  if (typeof rawBody === 'string' && rawBody.length > 0) {
    try {
      parsed = JSON.parse(rawBody)
    }
    catch {
      parsed = {}
    }
  }

  const text = typeof parsed.text === 'string'
    ? parsed.text
    : (typeof parsed.input === 'string' ? parsed.input : '')

  const voiceId = (typeof parsed.voice_id === 'string' && parsed.voice_id)
    ? parsed.voice_id
    : (typeof parsed.voice === 'string' && parsed.voice ? parsed.voice : defaultVoiceId)

  const speed = typeof parsed.speed === 'number' ? parsed.speed : 1.0
  const volume = typeof parsed.vol === 'number'
    ? parsed.vol
    : (typeof parsed.volume === 'number' ? parsed.volume : 1.0)
  const pitch = typeof parsed.pitch === 'number' ? parsed.pitch : 0

  const modelId = (() => {
    const m = typeof parsed.model === 'string' ? parsed.model : ''
    if (!m)
      return 'speech-2.5-hd-preview'
    // Accept both `speech-2.5-hd` and the official `speech-2.5-hd-preview`.
    if (m === 'speech-2.5-hd')
      return 'speech-2.5-hd-preview'
    if (m === 'speech-2.5-turbo')
      return 'speech-2.5-turbo-preview'
    return m
  })()

  return {
    model: modelId,
    text,
    stream: false,
    voice_setting: {
      voice_id: voiceId,
      speed,
      vol: volume,
      pitch,
    },
    audio_setting: {
      sample_rate: 32000,
      bitrate: 128000,
      format: 'mp3',
      channel: 1,
    },
  }
}
