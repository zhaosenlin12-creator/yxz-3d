<script setup lang="ts">
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import * as THREE from 'three'

import { resolveYXZModelUrl } from '@proj-airi/stage-ui/composables/use-yxz-print-preview'

const route = useRoute()
const canvas = ref<HTMLCanvasElement>()
const loading = ref(true)
const errorMessage = ref('')
// The model lives on the 宜小智 backend, not on the frontend origin: a
// relative path has to be resolved against the backend or the loader gets
// the app's own HTML page instead of a GLB.
const modelUrl = resolveYXZModelUrl(String(route.query.model ?? ''))
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
</script>

<template>
  <main class="yxz-preview-page">
    <header class="yxz-preview-header">
      <div>
        <span>宜小智</span>
        <strong>3D 模型预览</strong>
      </div>
      <a v-if="modelUrl" :href="`${modelUrl}${modelUrl.includes('?') ? '&' : '?'}download=1`" download>下载模型</a>
    </header>
    <section class="yxz-preview-viewer">
      <canvas ref="canvas" aria-label="宜小智 3D 模型预览" />
      <p v-if="loading" class="yxz-preview-state">正在加载模型…</p>
      <p v-if="errorMessage" class="yxz-preview-state error">{{ errorMessage }}</p>
      <small>拖动旋转 · 滚轮缩放 · 预览地址：{{ modelUrl }}</small>
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
.yxz-preview-header a { color: #087eae; text-decoration: underline; }
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
