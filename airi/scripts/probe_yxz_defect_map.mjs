/** Find the texture texels behind the marks on the model.
 *
 * The marks that read as damage on the head live in the base-colour
 * atlas, so repairing them means knowing which texel each mark is
 * drawn on.  The page cannot tell us that on its own: the camera is
 * rewritten whenever the canvas is resized, and the character keeps
 * moving, so a capture taken a second before a pick is looking at a
 * different part of the model.
 *
 * This therefore does the whole job in one go, inside one page
 * evaluation: it places the camera, renders the model into an
 * offscreen target, reads the pixels back, finds the marks in those
 * pixels, and casts a ray at each of them.  The picture that was
 * measured and the texels that were picked are the same frame, by
 * construction.
 *
 * Usage:
 *   node scripts/probe_yxz_defect_map.mjs <baseUrl> <shot> [x,y ...]
 *
 * With no points it finds the marks itself and reports them.
 */

import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

async function importPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return await import(pathToFileURL(require.resolve('playwright')).href)
  }
  catch {}
  const store = path.resolve('node_modules/.pnpm')
  const match = readdirSync(store).filter(e => e.startsWith('playwright@')).sort().at(-1)
  return import(pathToFileURL(path.join(store, match, 'node_modules', 'playwright', 'index.js')).href)
}

function resolveChromiumExecutable() {
  if (process.env.YXZ_CHROMIUM_PATH)
    return process.env.YXZ_CHROMIUM_PATH
  const root = path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  const revision = readdirSync(root)
    .filter(name => name.startsWith('chromium-'))
    .sort((a, b) => Number.parseInt(b.slice(9), 10) - Number.parseInt(a.slice(9), 10))[0]
  return path.join(root, revision, 'chrome-win64', 'chrome.exe')
}

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:5199'
const shot = process.argv[3] ?? 'crown'
const options = process.argv.slice(4).filter(value => value.startsWith('--'))
const pointArgs = process.argv.slice(4).filter(value => !value.startsWith('--'))
const manual = pointArgs.length === 1 && pointArgs[0].endsWith('.json')
  ? JSON.parse(readFileSync(pointArgs[0], 'utf8')).map(([x, y]) => ({ x, y }))
  : pointArgs.map(text => {
      const [x, y] = text.split(',').map(Number)
      return { x, y }
    })

const cameras = {
  head: { eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  crown: { eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  halo: { eye: [0, 3.3, 3.4], look: [0, 3.5, 0] },
  body: { eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
  visor: { eye: [0, 2.6, 2.2], look: [0, 2.42, 0.2] },
}
const placement = cameras[shot]
if (!placement)
  throw new Error('unknown shot: ' + shot)

const playwright = await importPlaywright()
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({
  executablePath: resolveChromiumExecutable(),
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})
try {
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 })
  await page.goto(`${baseUrl}/yxz-avatar`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForFunction(
    () => document.querySelector('.readout dd')?.textContent?.trim() === 'mounted',
    null,
    { timeout: 180_000 },
  )
  // The character's living layer keeps moving the head whatever the
  // mixer is doing, so the pose is paused before anything is measured.
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.evaluate(() => {
    const canvas = document.querySelector('.yxz-real-model-canvas canvas')
    for (const element of document.querySelectorAll('body *')) {
      if (element === canvas || element.contains(canvas))
        continue
      element.style.setProperty('display', 'none', 'important')
    }
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
  })
  // The page rewrites the camera whenever the canvas is resized, and the
  // capture and the pick have to be the same view, so the camera is
  // pinned on every frame rather than set once.
  await page.evaluate(([placement]) => {
    window.__yxzPin = placement
    const pin = () => {
      const camera = window.__yxzDebug?.camera?.()
      const wanted = window.__yxzPin
      if (camera && wanted) {
        camera.position.set(wanted.eye[0], wanted.eye[1], wanted.eye[2])
        camera.lookAt(wanted.look[0], wanted.look[1], wanted.look[2])
      }
      requestAnimationFrame(pin)
    }
    requestAnimationFrame(pin)
  }, [placement])
  // The layout settles after the rest of the page is hidden, and the
  // resize that follows moves the camera, so everything waits for the
  // canvas to stop changing size.
  await page.waitForTimeout(2500)
  await page.waitForTimeout(1200)

  const result = await page.evaluate(async ([placement, manual, options]) => {
    const debug = window.__yxzDebug
    const THREE = debug.three
    const scene = window.__yxzVrm.scene
    const renderer = debug.renderer()
    const camera = debug.camera()

    if (options.includes('--no-bloom'))
      debug.bloomPass().strength = 0
    if (options.includes('--no-outline') && debug.outlinePass())
      debug.outlinePass().enabled = false
    if (options.includes('--no-rim')) {
      debug.setUniform('parametricRimColorFactor', [0, 0, 0])
      debug.setUniform('rimLightingMixFactor', 0)
      debug.setUniform('parametricRimLiftFactor', 0)
    }

    camera.position.set(placement.eye[0], placement.eye[1], placement.eye[2])
    camera.lookAt(placement.look[0], placement.look[1], placement.look[2])
    camera.updateProjectionMatrix()
    scene.updateMatrixWorld(true)
    camera.updateMatrixWorld(true)

    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    const width = Math.max(1, Math.round(size.x))
    const height = Math.max(1, Math.round(size.y))

    // The frame is read out of the drawing buffer rather than out of an
    // offscreen target, because the drawing buffer holds what the page
    // shows: the tone map, the outline and the bloom are all in it.
    // Reading a target instead would give the linear image the shaders
    // wrote, and every threshold below would then be measuring the
    // wrong thing.
    const composer = debug.composer()
    if (composer)
      composer.render(0)
    else
      renderer.render(scene, camera)
    const gl = renderer.getContext()
    const pixels = new Uint8Array(width * height * 4)
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)

    // WebGL hands the frame back bottom-up.
    const at = (x, y) => {
      const row = height - 1 - y
      const offset = (row * width + x) * 4
      return [pixels[offset], pixels[offset + 1], pixels[offset + 2]]
    }

    const rays = new THREE.Raycaster()
    const cache = new Map()
    const atlasOf = (material) => {
      if (cache.has(material))
        return cache.get(material)
      const image = material.map?.image
      if (!image)
        return null
      const canvas = document.createElement('canvas')
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0)
      const entry = {
        pixels: context.getImageData(0, 0, canvas.width, canvas.height).data,
        width: image.width,
        height: image.height,
      }
      cache.set(material, entry)
      return entry
    }

    const pick = (x, y) => {
      rays.setFromCamera(
        new THREE.Vector2((x + 0.5) / width * 2 - 1, 1 - (y + 0.5) / height * 2),
        camera,
      )
      const rendered = at(x, y)
      const hit = rays.intersectObject(scene, true)[0]
      if (!hit)
        return { x, y, hit: false }
      const material = Array.isArray(hit.object.material)
        ? hit.object.material[hit.face.materialIndex]
        : hit.object.material
      const atlas = atlasOf(material)
      if (!atlas || !hit.uv)
        return { x, y, mesh: hit.object.name, texel: null }
      const column = Math.floor(hit.uv.x * (atlas.width - 1))
      const row = Math.floor(hit.uv.y * (atlas.height - 1))
      const offset = (row * atlas.width + column) * 4
      return {
        x,
        y,
        mesh: hit.object.name,
        material: material.name,
        rendered,
        faceIndex: hit.faceIndex,
        distance: hit.distance,
        normal: hit.face?.normal
          ?.clone()
          .applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld))
          .toArray(),
        texel: [column, row],
        colour: Array.from(atlas.pixels.slice(offset, offset + 3)),
        intersections: options.includes('--all-hits')
          ? rays.intersectObject(scene, true).slice(0, 12).map((other) => {
              const otherMaterial = Array.isArray(other.object.material)
                ? other.object.material[other.face.materialIndex]
                : other.object.material
              return {
                distance: other.distance,
                mesh: other.object.name,
                material: otherMaterial?.name,
                faceIndex: other.faceIndex,
                normal: other.face?.normal
                  ?.clone()
                  .applyMatrix3(new THREE.Matrix3().getNormalMatrix(other.object.matrixWorld))
                  .toArray(),
                uv: other.uv?.toArray(),
              }
            })
          : undefined,
      }
    }

    // A mark on the dark screen of the visor is a pale shape with the
    // dark screen all around it.  The eyes are pale too, but they are
    // round and large, so a mark is told apart by being small and by
    // having the screen, rather than the shell, around it.
    const isDark = ([r, g, b]) => r < 115 && g < 145 && b > 40 && b < 205
    const isPale = ([r, g, b]) => r > 150 && g > 170 && b > 175

    const found = []
    if (!manual.length) {
      const seen = new Uint8Array(width * height)
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          if (seen[y * width + x] || !isPale(at(x, y)))
            continue
          // Grow the pale patch.
          const stack = [[x, y]]
          const group = []
          while (stack.length) {
            const [cx, cy] = stack.pop()
            if (seen[cy * width + cx])
              continue
            seen[cy * width + cx] = 1
            if (!isPale(at(cx, cy)))
              continue
            group.push([cx, cy])
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
              const nx = cx + dx
              const ny = cy + dy
              if (nx < 0 || ny < 0 || nx >= width || ny >= height)
                continue
              if (!seen[ny * width + nx])
                stack.push([nx, ny])
            }
          }
          if (group.length < 12 || group.length > 6000)
            continue
          let dark = 0
          let ring = 0
          for (const [cx, cy] of group) {
            for (const [dx, dy] of [[3, 0], [-3, 0], [0, 3], [0, -3], [2, 2], [-2, 2], [2, -2], [-2, -2]]) {
              const nx = cx + dx
              const ny = cy + dy
              if (nx < 0 || ny < 0 || nx >= width || ny >= height)
                continue
              ring += 1
              if (isDark(at(nx, ny)))
                dark += 1
            }
          }
          if (!ring || dark / ring < 0.6)
            continue
          const step = Math.max(1, Math.floor(group.length / 12))
          const picks = group
            .filter((_, index) => index % step === 0)
            .slice(0, 12)
            .map(([cx, cy]) => pick(cx, cy))
          found.push({ area: group.length, picks })
        }
      }
    }
    else {
      found.push({ area: manual.length, picks: manual.map(point => pick(point.x, point.y)) })
    }

    // The picture that was measured, so the numbers can be checked
    // against the marks they came from.
    const picture = document.createElement('canvas')
    picture.width = width
    picture.height = height
    const context = picture.getContext('2d')
    const image = context.createImageData(width, height)
    for (let y = 0; y < height; y++) {
      const row = height - 1 - y
      for (let x = 0; x < width; x++) {
        const source = (row * width + x) * 4
        const target = (y * width + x) * 4
        image.data[target] = pixels[source]
        image.data[target + 1] = pixels[source + 1]
        image.data[target + 2] = pixels[source + 2]
        image.data[target + 3] = 255
      }
    }
    context.putImageData(image, 0, 0)
    context.strokeStyle = '#ff2d55'
    context.lineWidth = 2
    for (const entry of found) {
      for (const hit of entry.picks) {
        if (!hit)
          continue
        context.strokeRect(hit.x - 4, hit.y - 4, 8, 8)
      }
    }

    return {
      width,
      height,
      picture: picture.toDataURL('image/png'),
      found,
    }
  }, [placement, manual, options])

  const outDir = 'docs/yxz-audit'
  const suffix = options.length ? `-${options.map(value => value.slice(2)).join('-')}` : ''
  const png = Buffer.from(result.picture.split(',')[1], 'base64')
  writeFileSync(path.join(outDir, `defect-map-${shot}${suffix}.png`), png)
  writeFileSync(path.join(outDir, `defect-map-${shot}${suffix}.json`), JSON.stringify(result.found, null, 2))

  for (const entry of result.found) {
    const texels = entry.picks
      .filter(hit => hit?.texel)
      .map(hit => `${hit.x},${hit.y}=${hit.texel.join(':')}`)
    console.log(`MARK area=${entry.area} ${texels.join(' ')}`)
  }
  console.log(`MAP docs/yxz-audit/defect-map-${shot}${suffix}.png ${result.width}x${result.height}`)
}
finally {
  await browser.close()
}
