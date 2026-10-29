import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildYXZPreviewPrompt, createYXZCartoonModel, createYXZPreview, previewImageSrc, waitForYXZBackend, yxzBackendRecovery } from './use-yxz-print-preview'

afterEach(() => {
  yxzBackendRecovery.waitMs = 30_000
  yxzBackendRecovery.pollMs = 1_000
})

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

  it('waits for the backend to come back and repeats the same request', async () => {
    yxzBackendRecovery.pollMs = 5
    const providers: string[] = []
    let pingCalls = 0
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      if (String(input).includes('/api/ping')) {
        pingCalls += 1
        if (pingCalls === 1)
          throw new Error('connection refused')
        return new Response('{"ok":true}', { status: 200 })
      }
      providers.push(JSON.parse(String(init?.body)).prefer)
      if (providers.length === 1)
        throw new Error('network down')
      return new Response(JSON.stringify({
        session_id: 'retry1',
        prompt: '一个小猫摆件',
        previews: [{ index: 0, path: '/api/data/retry1/previews/img_0.png' }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZPreview({ prompt: '一个小猫摆件' }, fetcher)
    expect(result.sessionId).toBe('retry1')
    // The provider never failed -- the connection did.  So the retry has to
    // repeat the same provider instead of walking to a different one.
    expect(providers).toHaveLength(2)
    expect(providers[1]).toBe(providers[0])
  })

  it('falls back to another provider when the backend never comes back', async () => {
    yxzBackendRecovery.waitMs = 30
    yxzBackendRecovery.pollMs = 5
    const providers: string[] = []
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      if (String(input).includes('/api/ping'))
        throw new Error('backend down')
      providers.push(JSON.parse(String(init?.body)).prefer)
      throw new Error('network down')
    })

    await expect(createYXZPreview({ prompt: '一个小猫摆件' }, fetcher)).rejects.toThrow('预览没能生成出来')
    expect(providers.length).toBeGreaterThan(1)
    expect(providers[1]).not.toBe(providers[0])
  })

  it('does not walk the provider chain again when the backend already gave up', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"detail":"no image"}', { status: 500 }))
    await expect(createYXZPreview({ prompt: '测试' }, fetcher)).rejects.toThrow('预览没能生成出来')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('reports whether the backend came back for the retry', async () => {
    yxzBackendRecovery.pollMs = 5
    const down = vi.fn<typeof fetch>().mockRejectedValue(new Error('down'))
    await expect(waitForYXZBackend(40, down)).resolves.toBe(false)

    const up = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    await expect(waitForYXZBackend(1_000, up)).resolves.toBe(true)
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

  it('lets the backend run the whole engine chain', async () => {
    const urls: string[] = []
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [] }), { status: 200 })
      return new Response(JSON.stringify({
        session_id: 'abc123',
        model_url: '/api/data/abc123/model/mesh.glb',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZCartoonModel({ sessionId: 'abc123', imageIndex: 0 }, fetcher)
    expect(result.sessionId).toBe('abc123')
    // The build is one request: the engines are walked on the server, so a
    // refresh or a lost connection cannot kill a model that is being made.
    expect(urls.some(url => url.includes('/api/3d_build'))).toBe(true)
    expect(urls.some(url => url.includes('/api/3d_tripo'))).toBe(false)
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

  it('repeats the same 3D engine after the backend restarts', async () => {
    yxzBackendRecovery.pollMs = 5
    const endpoints: string[] = []
    let pingCalls = 0
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [] }), { status: 200 })
      if (url.includes('/api/ping')) {
        pingCalls += 1
        if (pingCalls === 1)
          throw new Error('connection refused')
        return new Response('{"ok":true}', { status: 200 })
      }
      endpoints.push(url)
      if (endpoints.length === 1)
        throw new Error('network down')
      return new Response(JSON.stringify({
        session_id: 'abc123',
        model_url: '/api/data/abc123/model/mesh.glb',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZCartoonModel({ sessionId: 'abc123', imageIndex: 0 }, fetcher)
    expect(result.sessionId).toBe('abc123')
    // Same build, not a different one: the transport broke, the backend did not.
    expect(endpoints).toHaveLength(2)
    expect(endpoints[1]).toBe(endpoints[0])
  })

  it('reports a build the backend refused', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      if (String(input).includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [] }), { status: 200 })
      return new Response('{"detail":"模型不合格"}', { status: 400 })
    })

    await expect(createYXZCartoonModel({ sessionId: 'abc123', imageIndex: 0 }, fetcher))
      .rejects.toThrow('模型不合格')
  })

  it('falls back to the browser chain when the backend has no server-side build', async () => {
    const endpoints: string[] = []
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/progress/'))
        return new Response(JSON.stringify({ events: [] }), { status: 200 })
      endpoints.push(url)
      if (url.includes('/api/3d_build'))
        return new Response('{"detail":"Not Found"}', { status: 404 })
      if (endpoints.length === 2)
        return new Response('{"detail":"模型不合格"}', { status: 400 })
      return new Response(JSON.stringify({
        session_id: 'abc123',
        model_url: '/api/data/abc123/model/mesh.glb',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const result = await createYXZCartoonModel({ sessionId: 'abc123', imageIndex: 0 }, fetcher)
    expect(result.sessionId).toBe('abc123')
    // The old chain walks the engines one after another.
    expect(endpoints.some(url => url.includes('/api/3d_tripo'))).toBe(true)
    expect(endpoints.some(url => url.includes('/api/3d_hycloud'))).toBe(true)
  })
})
