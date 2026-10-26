/** A/B the render stack without letting the pose move under the test.
 *
 * Every picture of this character taken from the browser a second
 * apart is of a different pose, because the head is alive.  That is
 * fine for looking at the character and useless for finding out what
 * made a mark: a texel that lands on a different pixel from one run to
 * the next cannot be compared against anything.
 *
 * So this does the whole comparison inside one evaluation.  The camera
 * is pinned, the character is parked, and then one change is made to
 * the render stack at a time and the frame is read back.  Because
 * nothing is allowed to advance in between, every variant is a
 * picture of the same pose, and a difference between two of them can
 * only be the change that was made.
 *
 * Usage:
 *   node scripts/probe_yxz_ab.mjs <baseUrl> <shot> <outDir> [x,y ...]
 */

import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
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
const outDir = process.argv[4] ?? 'docs/yxz-audit/ab'
const points = process.argv.slice(5)
  .filter(value => !value.startsWith('--'))
  .map(text => {
    const [x, y] = text.split(',').map(Number)
    return { x, y }
  })

const cameras = {
  head: { eye: [0, 2.52, 3.1], look: [0, 2.45, 0.5] },
  crown: { eye: [0.4, 3.4, 2.6], look: [0, 2.9, 0.4] },
  face: { eye: [0, 2.5, 1.95], look: [0, 2.42, 0.3] },
  body: { eye: [0, 1.9, 3.2], look: [0, 1.85, 0.3] },
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
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await page.evaluate(([placement]) => {
    const canvas = document.querySelector('.yxz-real-model-canvas canvas')
    for (const element of document.querySelectorAll('body *')) {
      if (element === canvas || element.contains(canvas))
        continue
      element.style.setProperty('display', 'none', 'important')
    }
    window.__yxzDebug?.freeze(true)
    window.__yxzDebug?.snap?.('YXZ_Idle', 0.7)
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
  await page.waitForTimeout(2500)
  await page.waitForTimeout(1200)

  const result = await page.evaluate(async ([placement, points]) => {
    const debug = window.__yxzDebug
    const THREE = debug.three
    const scene = window.__yxzVrm.scene
    const renderer = debug.renderer()
    const camera = debug.camera()
    const composer = debug.composer()

    camera.position.set(placement.eye[0], placement.eye[1], placement.eye[2])
    camera.lookAt(placement.look[0], placement.look[1], placement.look[2])
    camera.updateProjectionMatrix()
    scene.updateMatrixWorld(true)
    camera.updateMatrixWorld(true)

    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    const width = Math.max(1, Math.round(size.x))
    const height = Math.max(1, Math.round(size.y))
    const buffer = new Uint8Array(width * height * 4)

    const draw = () => {
      if (composer)
        composer.render(0)
      else
        renderer.render(scene, camera)
      const gl = renderer.getContext()
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, buffer)
    }

    const picture = () => {
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const context = canvas.getContext('2d')
      const image = context.createImageData(width, height)
      for (let y = 0; y < height; y++) {
        const row = height - 1 - y
        for (let x = 0; x < width; x++) {
          const source = (row * width + x) * 4
          const target = (y * width + x) * 4
          image.data[target] = buffer[source]
          image.data[target + 1] = buffer[source + 1]
          image.data[target + 2] = buffer[source + 2]
          image.data[target + 3] = 255
        }
      }
      context.putImageData(image, 0, 0)
      return canvas.toDataURL('image/png')
    }

    const at = (x, y) => {
      const row = height - 1 - y
      const offset = (row * width + x) * 4
      return [buffer[offset], buffer[offset + 1], buffer[offset + 2]]
    }

    const character = []
    scene.traverse((object) => {
      if (object.isMesh && object.material?.isMToonMaterial)
        character.push(object)
    })
    const lights = {}
    for (const name of ['hemisphere', 'key', 'fill', 'frontal', 'rim', 'bounce']) {
      const light = scene.getObjectByName(name)
      if (light)
        lights[name] = light
    }
    const savedMap = character.map(mesh => mesh.material.map)

    // Every variant starts from the same stack, so a difference between
    // two of them can only be the change that was made.
    const restore = () => {
      if (debug.bloomPass())
        debug.bloomPass().strength = saved.bloom
      if (debug.bloomPass()) {
        debug.bloomPass().radius = saved.bloomRadius
        debug.bloomPass().threshold = saved.bloomThreshold
      }
      if (debug.outlinePass())
        debug.outlinePass().enabled = saved.outline
      debug.setSide(debug.three.DoubleSide)
      for (const name of Object.keys(lights))
        lights[name].intensity = saved.lights[name]
      character.forEach((mesh, index) => {
        mesh.material.map = savedMap[index]
        mesh.material.color.setRGB(1, 1, 1)
        mesh.material.needsUpdate = true
      })
      debug.setUniform('parametricRimColorFactor', saved.rimColor)
      debug.setUniform('rimLightingMixFactor', saved.rimMix)
      debug.setUniform('parametricRimFresnelPowerFactor', saved.rimPower)
      debug.setUniform('parametricRimLiftFactor', saved.rimLift)
    }

    const saved = {
      bloom: debug.bloomPass()?.strength ?? 0,
      bloomRadius: debug.bloomPass()?.radius ?? 0,
      bloomThreshold: debug.bloomPass()?.threshold ?? 0,
      outline: debug.outlinePass()?.enabled ?? true,
      lights: Object.fromEntries(Object.entries(lights).map(([name, light]) => [name, light.intensity])),
      rimColor: [0.52, 0.63, 0.84],
      rimMix: 0.06,
      rimPower: 2.4,
      rimLift: 0.12,
    }

    const rim = (colour, mix, power, lift) => {
      debug.setUniform('parametricRimColorFactor', colour)
      debug.setUniform('rimLightingMixFactor', mix)
      debug.setUniform('parametricRimFresnelPowerFactor', power)
      debug.setUniform('parametricRimLiftFactor', lift)
    }

    const bloom = (strength, threshold, radius) => {
      const pass = debug.bloomPass()
      if (!pass)
        return
      pass.strength = strength
      pass.threshold = threshold
      pass.radius = radius
    }

    const candidate = (colour, mix, power, lift, strength, threshold, radius) => {
      rim(colour, mix, power, lift)
      bloom(strength, threshold, radius)
    }

    const variants = [
      { name: 'baseline' },
      { name: 'front-side', apply: () => debug.setSide(debug.three.FrontSide) },
      {
        name: 'front-side-tripo',
        apply: () => {
          let touched = 0
          scene.traverse((object) => {
            if (!object.isMesh)
              return
            const materials = Array.isArray(object.material) ? object.material : [object.material]
            for (const material of materials) {
              if (!material.name.startsWith('tripo_'))
                continue
              material.side = debug.three.FrontSide
              material.needsUpdate = true
              touched++
            }
          })
          return touched
        },
      },
      {
        name: 'front-side-no-outline',
        apply: () => {
          debug.setSide(debug.three.FrontSide)
          if (debug.outlinePass())
            debug.outlinePass().enabled = false
        },
      },
      { name: 'no-bloom', apply: () => { if (debug.bloomPass()) debug.bloomPass().strength = 0 } },
      { name: 'no-outline', apply: () => { if (debug.outlinePass()) debug.outlinePass().enabled = false } },
      { name: 'rim-off', apply: () => rim([0, 0, 0], 0, 2.4, 0) },
      { name: 'rim-lift0', apply: () => rim([0.52, 0.63, 0.84], 0.06, 2.4, 0) },
      { name: 'rim-soft', apply: () => rim([0.30, 0.37, 0.50], 0.06, 3.0, 0.02) },
      { name: 'rim-tighter', apply: () => rim([0.22, 0.28, 0.40], 0.06, 3.6, 0.0) },
      { name: 'rim-faint', apply: () => rim([0.14, 0.18, 0.27], 0.06, 2.8, 0.0) },
      {
        name: 'candidate',
        apply: () => candidate([0.22, 0.28, 0.40], 0.06, 3.6, 0.0, 0.95, 1.55, 0.65),
      },
      {
        name: 'candidate-soft-bloom',
        apply: () => candidate([0.22, 0.28, 0.40], 0.06, 3.6, 0.0, 0.55, 1.9, 0.6),
      },
      {
        name: 'candidate-no-bloom',
        apply: () => candidate([0.22, 0.28, 0.40], 0.06, 3.6, 0.0, 0.0, 1.9, 0.6),
      },
      { name: 'no-bounce', apply: () => { if (lights.bounce) lights.bounce.intensity = 0 } },
      { name: 'no-rim-light', apply: () => { if (lights.rim) lights.rim.intensity = 0 } },
      { name: 'no-hemisphere', apply: () => { if (lights.hemisphere) lights.hemisphere.intensity = 0 } },
      { name: 'no-fill', apply: () => { if (lights.fill) lights.fill.intensity = 0 } },
      { name: 'no-frontal', apply: () => { if (lights.frontal) lights.frontal.intensity = 0 } },
      { name: 'no-key', apply: () => { if (lights.key) lights.key.intensity = 0 } },
      {
        name: 'flat-texture',
        apply: () => {
          for (const mesh of character) {
            mesh.material.map = null
            mesh.material.color.setRGB(0.75, 0.75, 0.78)
            mesh.material.needsUpdate = true
          }
        },
      },
    ]

    const results = []
    for (const variant of variants) {
      restore()
      const changed = variant.apply?.() ?? 0
      draw()
      let pale = 0
      let bright = 0
      for (let i = 0; i < buffer.length; i += 4) {
        const value = (buffer[i] + buffer[i + 1] + buffer[i + 2]) / 3
        if (value > 200)
          pale++
        if (value > 245)
          bright++
      }
      results.push({
        name: variant.name,
        changed,
        pale,
        bright,
        points: points.map(point => ({ ...point, colour: at(point.x, point.y) })),
        png: picture(),
      })
    }

    restore()

    return { width, height, results }
  }, [placement, points])

  mkdirSync(outDir, { recursive: true })
  const table = []
  for (const entry of result.results) {
    writeFileSync(
      path.join(outDir, `${entry.name}.png`),
      Buffer.from(entry.png.split(',')[1], 'base64'),
    )
    const samples = entry.points
      .map(point => `${point.x},${point.y}=${point.colour.join('/')}`)
      .join('  ')
    table.push(`${entry.name.padEnd(24)} changed=${String(entry.changed).padStart(3)} pale=${String(entry.pale).padStart(7)} bright=${String(entry.bright).padStart(7)}  ${samples}`)
  }
  console.log(table.join('\n'))
  console.log(`AB ${outDir}`)
}
finally {
  await browser.close()
}
