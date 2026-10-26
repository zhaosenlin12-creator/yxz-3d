import { describe, expect, it, vi } from 'vitest'

import { buildYXZPreviewPrompt, createYXZCartoonModel, createYXZPreview, previewImageSrc } from './use-yxz-print-preview'

describe('YXZ print preview adapter', () => {
  it('adds selected design constraints without changing the original description', () => {
    expect(buildYXZPreviewPrompt('一个小猫摆件', ['圆润可爱', '适合 3D 打印']))
      .toBe('一个小猫摆件\n\n设计约束：圆润可爱、适合 3D 打印')
  })

  it('normalizes backend preview payloads and image URLs', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      session_id: 'abc123',
      prompt: '一个小猫摆件',
      previews: [{ index: 0, b64: 'ZmFrZQ==', caption: '正面' }, { index: 1, path: '/api/data/abc/previews/img_1.png' }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    const result = await createYXZPreview({ prompt: '一个小猫摆件', sessionId: 'abc123' }, fetcher)
    expect(result.sessionId).toBe('abc123')
    expect(result.previews).toHaveLength(2)
    expect(previewImageSrc(result.previews[0])).toBe('data:image/png;base64,ZmFrZQ==')
    expect(previewImageSrc(result.previews[1], 'http://127.0.0.1:8000'))
      .toBe('http://127.0.0.1:8000/api/data/abc/previews/img_1.png')
  })

  it('rejects malformed responses instead of rendering untrusted data', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 200 }))
    await expect(createYXZPreview({ prompt: '测试' }, fetcher)).rejects.toThrow('数据格式')
  })

  it('builds printable model and export URLs from the session response', async () => {
    const progress = [] as Array<{ percent: number, message: string }>
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      if (String(input).includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [{ ts: 1, percent: 40, message: '构建浮雕' }] }), { status: 200 })
      return new Response(JSON.stringify({
        session_id: 'abc123',
        model_url: '/api/data/abc123/model/mesh.glb',
        faces: 1200,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZCartoonModel({ sessionId: 'abc123', imageIndex: 1, onProgress: value => progress.push(value) }, fetcher)
    expect(result.modelUrl).toContain('/api/data/abc123/model/mesh.glb')
    expect(result.stlUrl).toContain('/api/export/abc123/stl')
    expect(result.glbUrl).toContain('/api/export/abc123/glb')
    expect(progress.some(value => value.message === '构建浮雕' && value.percent === 40)).toBe(true)
  })

  it('sends a canvas-edited image when creating the printable model', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      if (String(input).includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [] }), { status: 200 })

      const body = JSON.parse(String(init?.body)) as { custom_image?: string }
      expect(body.custom_image).toBe('data:image/png;base64,edited')
      return new Response(JSON.stringify({
        session_id: 'edited123',
        model_url: '/api/data/edited123/model/mesh.glb',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZCartoonModel({
      sessionId: 'edited123',
      imageIndex: 0,
      customImage: 'data:image/png;base64,edited',
    }, fetcher)

    expect(result.sessionId).toBe('edited123')
  })
})
