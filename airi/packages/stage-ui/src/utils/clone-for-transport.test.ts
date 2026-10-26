import { describe, expect, it } from 'vitest'

import { cloneForTransport } from './clone-for-transport'

describe('cloneForTransport', () => {
  it('keeps ordinary values cloneable', () => {
    expect(cloneForTransport({ text: '你好', count: 2 })).toEqual({ text: '你好', count: 2 })
  })

  it('sanitizes tool payloads that contain functions and cycles', () => {
    const payload: Record<string, unknown> = { text: '预览已生成', callback: () => undefined }
    payload.self = payload

    expect(cloneForTransport(payload)).toEqual({
      text: '预览已生成',
      self: '[Circular]',
    })
  })
})
