<script setup lang="ts">
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import * as THREE from 'three'

import { detectYXZLocalSoftware, openYXZExportInSoftware, resolveYXZModelUrl } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'

import type { YXZLocalSoftware } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'

const route = useRoute()
const canvas = ref<HTMLCanvasElement>()
const loading = ref(true)
const errorMessage = ref('')
// The model lives on the 宜小智 backend, not on the frontend origin: a
// relative path has to be resolved against the backend or the loader gets
// the app's own HTML page instead of a GLB.
const modelUrl = resolveYXZModelUrl(String(route.query.model ?? ''))
// The session the model belongs to.  With it the page can hand the mesh to
// the slicer on this machine; without it all we can offer is a download.
const sessionId = String(route.query.sid ?? '').trim()
// A preset model has no session; it lives in the project's preset folder.
const presetName = String(route.query.preset ?? '').trim()
const localSoftware = ref<YXZLocalSoftware[]>([])
const softwareLoading = ref(false)
const openingSoftwareId = ref<string>()
const softwareMessage = ref('')
const canOpenInSoftware = computed(() => Boolean(sessionId || presetName))
// Which axis of the file is the height. The print pipeline scales the Z
// axis to the requested height, so a finished model is Z-up; a raw model
// from the 3D service can differ, and the caller knows which it is.
const upAxis = String(route.query.up ?? '').trim().toLowerCase()
let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene | undefined
let camera: THREE.PerspectiveCamera | undefined
let controls: OrbitControls | undefined
let frame = 0

const AXIS_NAMES = ['x', 'y', 'z'] as const

/**
 * Work out how the model has to be turned so that it is shown the way it
 * will be printed.
 *
 * The thickness of a printable model is always its smallest dimension, and
 * the thinnest axis has to point *away* from the camera - otherwise a flat
 * relief is only visible edge on and looks like a sliver. Of the two
 * remaining axes the taller one is the height; when the two are nearly the
 * same the print convention (Z) wins, because that is the axis the print
 * pipeline scaled.
 */
function pickOrientation(size: THREE.Vector3, hint: string) {
  const extents = [size.x, size.y, size.z]
  const sorted = [0, 1, 2].sort((a, b) => extents[a] - extents[b])
  const thin = sorted[0]
  const rest = sorted.slice(1)

  const hintIndex = AXIS_NAMES.indexOf(hint as (typeof AXIS_NAMES)[number])
  let up: number
  if (hintIndex >= 0 && hintIndex !== thin) {
    up = hintIndex
  }
  else {
    const [shorter, taller] = rest
    const nearlyEqual = Math.abs(extents[shorter] - extents[taller]) / Math.max(extents[shorter], extents[taller]) < 0.25
    up = nearlyEqual && rest.includes(2) ? 2 : taller
  }

  const width = rest.find(index => index !== up) ?? rest[0]
  return { thin, up, width }
}

/**
 * Turn the model into the orientation the printer expects.
 *
 * The axes are swapped, which can turn the rotation into a mirror image.
 * Flipping the depth axis keeps it a proper rotation and leaves the model
 * upright, it only decides which side of it faces the camera.
 */
function applyOrientation(model: THREE.Object3D, size: THREE.Vector3, hint: string) {
  const { thin, up, width } = pickOrientation(size, hint)
  const images = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()]
  images[width].set(1, 0, 0)
  images[up].set(0, 1, 0)
  images[thin].set(0, 0, 1)

  const matrix = new THREE.Matrix4().makeBasis(images[0], images[1], images[2])
  if (matrix.determinant() < 0) {
    images[thin].set(0, 0, -1)
    matrix.makeBasis(images[0], images[1], images[2])
  }
  model.quaternion.setFromRotationMatrix(matrix)
  model.updateMatrixWorld(true)
}

function resize() {
  if (!renderer || !camera || !canvas.value)
    return
  const width = Math.max(1, canvas.value.clientWidth)
  const height = Math.max(1, canvas.value.clientHeight)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height, false)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
}

function startViewer() {
  if (!canvas.value || !modelUrl) {
    loading.value = false
    errorMessage.value = '没有可预览的模型地址'
    return
  }
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xF5FCFF)
  camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100)
  camera.position.set(0, 1.2, 4.5)
  renderer = new THREE.WebGLRenderer({ canvas: canvas.value, antialias: true, alpha: true })
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1
  scene.add(new THREE.HemisphereLight(0xE8F8FF, 0x17334C, 2.2))
  const key = new THREE.DirectionalLight(0xFFFFFF, 3)
  key.position.set(3, 5, 4)
  scene.add(key)
  controls = new OrbitControls(camera, canvas.value)
  controls.enableDamping = true
  controls.target.set(0, 1.2, 0)

  const draco = new DRACOLoader().setDecoderPath('/draco/')
  const loader = new GLTFLoader().setDRACOLoader(draco)
  loader.load(modelUrl, (gltf) => {
    if (!scene || !camera || !controls)
      return
    const model = gltf.scene
    // Models come from Tripo (Y-up), from Hunyuan3D (Z-up once it went
    // through the print prep) or from a local export. Turn every one of
    // them into the print orientation: the thinnest axis points away from
    // the camera and the height points up.
    const rawBox = new THREE.Box3().setFromObject(model)
    const rawSize = rawBox.getSize(new THREE.Vector3())
    applyOrientation(model, rawSize, upAxis)
    const box = new THREE.Box3().setFromObject(model)
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const maxDimension = Math.max(size.x, size.y, size.z, 0.001)
    const scale = 2.8 / maxDimension
    model.scale.setScalar(scale)
    model.position.set(-center.x * scale, -center.y * scale, -center.z * scale)
    scene.add(model)
    const framedBox = new THREE.Box3().setFromObject(model)
    const framedSphere = framedBox.getBoundingSphere(new THREE.Sphere())
    const halfFov = THREE.MathUtils.degToRad(camera.fov / 2)
    const fitDistance = (framedSphere.radius / Math.max(Math.sin(halfFov), 0.1)) * 1.25
    camera.position.set(0, 0, Math.max(fitDistance, 3.8))
    camera.near = Math.max(0.01, fitDistance / 100)
    camera.far = Math.max(100, fitDistance * 20)
    camera.updateProjectionMatrix()
    controls.target.set(0, 0, 0)
    controls.update()
    loading.value = false
  }, undefined, (error) => {
    loading.value = false
    errorMessage.value = '模型加载失败，请检查宜小智服务是否仍在运行'
    console.error('宜小智模型预览加载失败', error)
  })
  resize()
  const animate = () => {
    frame = requestAnimationFrame(animate)
    controls?.update()
    if (scene && camera && renderer)
      renderer.render(scene, camera)
  }
  animate()
  window.addEventListener('resize', resize)
}

onMounted(startViewer)
onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  window.removeEventListener('resize', resize)
  controls?.dispose()
  renderer?.dispose()
})

/**
 * Look for slicers / editors installed on this machine.
 *
 * The visitor stands in front of the screen, so the model has to be able
 * to leave the browser: the button says "交给软件打印" and hands the mesh
 * to whichever slicer is installed.
 */
async function detectLocalSoftware() {
  if (softwareLoading.value)
    return
  softwareLoading.value = true
  softwareMessage.value = ''
  try {
    localSoftware.value = await detectYXZLocalSoftware()
    const count = localSoftware.value.filter(tool => tool.available).length
    softwareMessage.value = count ? `已找到 ${count} 个可用软件` : '暂未找到已安装的软件'
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '软件检测失败，请确认打印服务已启动'
  }
  finally {
    softwareLoading.value = false
  }
}

async function openInLocalSoftware(tool: YXZLocalSoftware) {
  if (!canOpenInSoftware.value || openingSoftwareId.value)
    return
  openingSoftwareId.value = tool.id
  softwareMessage.value = ''
  try {
    const resp = await openYXZExportInSoftware({
      softwareId: tool.id,
      sessionId: sessionId || undefined,
      format: 'stl',
      ...(presetName ? { path: `presets/models/${presetName}/model.stl` } : {}),
    })
    const data = await resp.json().catch(() => ({})) as { message?: string }
    softwareMessage.value = data?.message || `已打开 ${tool.name}，请在软件里确认参数后再打印`
  }
  catch (error) {
    softwareMessage.value = error instanceof Error ? error.message : '打开软件失败'
  }
  finally {
    openingSoftwareId.value = undefined
  }
}

// Auto-detect once the model is on screen: the visitor should not have to
// hunt for a button to find out what they can print with.
onMounted(() => {
  if (canOpenInSoftware.value)
    void detectLocalSoftware()
})
</script>

<template>
  <main class="yxz-preview-page">
    <header class="yxz-preview-header">
      <div>
        <span>宜小智</span>
        <strong>3D 模型预览</strong>
      </div>
      <div class="yxz-preview-actions">
        <button
          v-if="canOpenInSoftware"
          type="button"
          class="yxz-preview-button"
          :disabled="softwareLoading"
          @click="detectLocalSoftware"
        >
          {{ softwareLoading ? '检测中…' : '检测本机软件' }}
        </button>
        <a
          v-if="modelUrl"
          class="yxz-preview-button ghost"
          :href="`${modelUrl}${modelUrl.includes('?') ? '&' : '?'}download=1`"
          download
        >
          下载模型
        </a>
      </div>
    </header>
    <div v-if="canOpenInSoftware" class="yxz-preview-software">
      <div v-if="localSoftware.some(tool => tool.available)" class="yxz-preview-software-list" aria-label="本机软件">
        <button
          v-for="tool in localSoftware.filter(tool => tool.available)"
          :key="tool.id"
          type="button"
          class="yxz-preview-button"
          :disabled="openingSoftwareId === tool.id"
          @click="openInLocalSoftware(tool)"
        >
          {{ openingSoftwareId === tool.id ? '打开中…' : `用 ${tool.name} 打印` }}
        </button>
      </div>
      <small v-if="softwareMessage" class="yxz-preview-software-message">{{ softwareMessage }}</small>
    </div>
    <section class="yxz-preview-viewer">
      <canvas ref="canvas" aria-label="宜小智 3D 模型预览" />
      <p v-if="loading" class="yxz-preview-state">正在加载模型…</p>
      <p v-if="errorMessage" class="yxz-preview-state error">{{ errorMessage }}</p>
      <small>拖动旋转 · 滚轮缩放</small>
    </section>
  </main>
</template>

<style scoped>
.yxz-preview-page {
  min-height: 100dvh;
  padding: 1.2rem;
  background: linear-gradient(150deg, #f5fcff, #e5f7fd);
  color: #15547c;
}
.yxz-preview-header {
  display: flex;
  max-width: 72rem;
  margin: 0 auto 1rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.yxz-preview-header div { display: flex; flex-direction: column; gap: .2rem; }
.yxz-preview-header span { color: #087eae; font-size: .78rem; }
.yxz-preview-header strong { font-size: 1.25rem; }
.yxz-preview-actions {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: .5rem;
}
.yxz-preview-button {
  padding: .55rem 1.1rem;
  border: 1px solid #0b7fb4;
  border-radius: .55rem;
  background: #0b7fb4;
  color: #f7fdff;
  font: inherit;
  font-size: .9rem;
  line-height: 1.2;
  text-decoration: none;
  cursor: pointer;
}
.yxz-preview-button:hover:not(:disabled) { background: #086a99; border-color: #086a99; }
.yxz-preview-button:disabled { opacity: .55; cursor: progress; }
.yxz-preview-button.ghost {
  border-color: #7db9d4;
  background: transparent;
  color: #0b7fb4;
}
.yxz-preview-button.ghost:hover:not(:disabled) { background: #dff2fb; border-color: #0b7fb4; }
.yxz-preview-software {
  display: flex;
  max-width: 72rem;
  margin: 0 auto .8rem;
  flex-wrap: wrap;
  align-items: center;
  gap: .6rem;
}
.yxz-preview-software-list { display: flex; flex-wrap: wrap; gap: .5rem; }
.yxz-preview-software-message { color: #52758a; }
.yxz-preview-viewer {
  position: relative;
  max-width: 72rem;
  height: min(78dvh, 52rem);
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid #b5dce9;
  border-radius: 1.2rem;
  background: #f5fcff;
  box-shadow: 0 18px 50px rgba(25, 110, 150, .14);
}
.yxz-preview-viewer canvas { display: block; width: 100%; height: 100%; }
.yxz-preview-state { position: absolute; inset: 50% auto auto 50%; transform: translate(-50%, -50%); color: #52758a; }
.yxz-preview-state.error { color: #b34646; }
.yxz-preview-viewer small { position: absolute; right: 1rem; bottom: .8rem; left: 1rem; overflow: hidden; color: #6b8798; text-overflow: ellipsis; white-space: nowrap; }
</style>

<route lang="yaml">
name: YXZPreviewPage
meta:
  layout: plain
</route>
