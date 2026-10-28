import { afterEach, describe, expect, it, vi } from 'vitest'

import { useYXZVoiceInput } from './use-yxz-voice-input'

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = []
  static payloadSize = 4096

  mimeType = 'audio/webm;codecs=opus'
  state = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  private listeners: Array<() => void> = []

  constructor(public stream: MediaStream) {
    FakeMediaRecorder.instances.push(this)
  }

  static isTypeSupported() {
    return true
  }

  start() {
    this.state = 'recording'
  }

  addEventListener(name: string, handler: () => void) {
    if (name === 'stop')
      this.listeners.push(handler)
  }

  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([new Uint8Array(FakeMediaRecorder.payloadSize)], { type: this.mimeType }) })
    this.listeners.splice(0).forEach(handler => handler())
  }
}

function fakeStream() {
  return { id: 'fake', getTracks: () => [{ stop: () => {} }] } as unknown as MediaStream
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeMediaRecorder.instances = []
  FakeMediaRecorder.payloadSize = 4096
})

describe('YXZ voice input', () => {
  it('records, transcribes locally and hands the text over', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      text: '我想做一个可爱的桌面摆件',
      duration: 2.3,
      elapsed: 1.9,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream()) },
    })

    const onText = vi.fn()
    const voice = useYXZVoiceInput({ onText })

    const started = await voice.start()
    expect(started).toBe(true)
    expect(voice.state.value).toBe('recording')

    await voice.stop()

    expect(voice.state.value).toBe('idle')
    expect(onText).toHaveBeenCalledWith('我想做一个可爱的桌面摆件')
    const [url] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/asr/transcribe')
  })

  it('reports a missing microphone instead of failing silently', async () => {
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockRejectedValue(Object.assign(new Error('denied'), { name: 'NotAllowedError' })),
      },
    })

    const onError = vi.fn()
    const voice = useYXZVoiceInput({ onError })

    const started = await voice.start()
    expect(started).toBe(false)
    expect(voice.state.value).toBe('error')
    expect(onError).toHaveBeenCalled()
    expect(String(onError.mock.calls[0][0])).toContain('麦克风')
  })

  it('says so when the clip is too short to be speech', async () => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream()) },
    })
    FakeMediaRecorder.payloadSize = 16

    const onError = vi.fn()
    const voice = useYXZVoiceInput({ onError })
    await voice.start()
    await voice.stop()

    expect(onError).toHaveBeenCalled()
    expect(String(onError.mock.calls[0][0])).toContain('没有听到声音')
  })
})
