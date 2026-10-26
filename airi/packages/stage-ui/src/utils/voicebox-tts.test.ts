import { describe, expect, it } from 'vitest'

import { buildVoiceboxTtsBody } from './voicebox-tts'

describe('Voicebox TTS adapter', () => {
  it('maps Chinese speech to a Voicebox Qwen CustomVoice request', () => {
    const body = buildVoiceboxTtsBody(JSON.stringify({
      input: '你好，我是宜小智。',
      voice: 'profile-eric',
    }))

    expect(body).toMatchObject({
      profile_id: 'profile-eric',
      language: 'zh',
      engine: 'qwen_custom_voice',
      model_size: '1.7B',
    })
    expect(body.instruct).toContain('卡通感')
  })

  it('uses configured defaults when the upstream body has no voice', () => {
    const body = buildVoiceboxTtsBody(JSON.stringify({ input: 'Hello' }), {
      defaultProfileId: 'profile-dylan',
      defaultLanguage: 'zh',
      modelSize: '0.6B',
      instruct: '清晰、轻快。',
    })

    expect(body).toMatchObject({
      profile_id: 'profile-dylan',
      language: 'zh',
      model_size: '0.6B',
      instruct: '清晰、轻快。',
    })
  })
})
