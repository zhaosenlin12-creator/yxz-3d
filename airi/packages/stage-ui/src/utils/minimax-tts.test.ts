import { describe, expect, it } from 'vitest'

import { buildMinimaxTtsBody } from './minimax-tts'

// https://github.com/moeru-ai/airi/issues -- TTS English-fallback / incomplete playback bug
describe('buildMinimaxTtsBody', () => {
  it('translates an OpenAI-style body to the MiniMax t2a_v2 shape', () => {
    const upstream = JSON.stringify({
      model: 'speech-2.5-hd',
      input: '你好世界',
      voice: 'female-shaonv',
      speed: 1.2,
      vol: 0.9,
      pitch: -2,
    })

    const body = buildMinimaxTtsBody(upstream)

    expect(body.model).toBe('speech-2.5-hd-preview')
    expect(body.text).toBe('你好世界')
    expect(body.voice_setting).toEqual({
      voice_id: 'female-shaonv',
      speed: 1.2,
      vol: 0.9,
      pitch: -2,
    })
    expect(body.audio_setting).toEqual({
      sample_rate: 32000,
      bitrate: 128000,
      format: 'mp3',
      channel: 1,
    })
    expect(body.stream).toBe(false)
  })

  it('keeps the full upstream text instead of truncating it (regression for the incomplete-playback bug)', () => {
    const longText = '这是一段非常长的中文回复。'.repeat(40)
    const upstream = JSON.stringify({
      model: 'speech-2.5-hd',
      input: longText,
      voice: 'female-shaonv',
    })

    const body = buildMinimaxTtsBody(upstream)

    expect(body.text).toBe(longText)
    expect(body.text.length).toBe(longText.length)
  })

  it('falls back to the default Chinese voice when the upstream voice is missing', () => {
    const body = buildMinimaxTtsBody(JSON.stringify({ input: 'hello' }))

    expect(body.voice_setting.voice_id).toBe('female-shaonv')
  })

  it('honours a custom defaultVoiceId option', () => {
    const body = buildMinimaxTtsBody(JSON.stringify({ input: 'hello' }), { defaultVoiceId: 'English_Graceful_Lady' })

    expect(body.voice_setting.voice_id).toBe('English_Graceful_Lady')
  })

  it('maps the official model aliases to their preview ids', () => {
    expect(buildMinimaxTtsBody(JSON.stringify({ model: 'speech-2.5-hd', input: 'x' })).model).toBe('speech-2.5-hd-preview')
    expect(buildMinimaxTtsBody(JSON.stringify({ model: 'speech-2.5-turbo', input: 'x' })).model).toBe('speech-2.5-turbo-preview')
  })

  it('passes through unknown model ids untouched', () => {
    const body = buildMinimaxTtsBody(JSON.stringify({ model: 'speech-02-experimental', input: 'x' }))

    expect(body.model).toBe('speech-02-experimental')
  })

  it('uses safe defaults for speed / volume / pitch when missing', () => {
    const body = buildMinimaxTtsBody(JSON.stringify({ input: 'hi' }))

    expect(body.voice_setting.speed).toBe(1.0)
    expect(body.voice_setting.vol).toBe(1.0)
    expect(body.voice_setting.pitch).toBe(0)
  })

  it('falls back to an empty text and default voice on malformed input', () => {
    const body = buildMinimaxTtsBody('not-json{')

    expect(body.text).toBe('')
    expect(body.voice_setting.voice_id).toBe('female-shaonv')
    expect(body.model).toBe('speech-2.5-hd-preview')
  })

  it('treats an undefined body as an empty upstream request', () => {
    const body = buildMinimaxTtsBody(undefined)

    expect(body.text).toBe('')
    expect(body.voice_setting.voice_id).toBe('female-shaonv')
  })

  it('prefers `voice_id` over `voice` when both are present', () => {
    const body = buildMinimaxTtsBody(JSON.stringify({
      input: 'hi',
      voice: 'English_Graceful_Lady',
      voice_id: 'female-shaonv',
    }))

    expect(body.voice_setting.voice_id).toBe('female-shaonv')
  })
})
