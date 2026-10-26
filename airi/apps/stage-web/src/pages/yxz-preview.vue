<script setup lang="ts">
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import * as THREE from 'three'

const route = useRoute()
const canvas = ref<HTMLCanvasElement>()
const loading = ref(true)
const errorMessage = ref('')
const modelUrl = String(route.query.model ?? '')
let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene | undefined
let camera: THREE.PerspectiveCamera | undefined
let controls: OrbitControls | undefined
let frame = 0

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
    // The print backend exports meshes with Z-up coordinates. The web viewer
    // is Y-up, so normalize the orientation before framing; otherwise a
    // plaque/figurine is presented edge-on and appears stretched or clipped.
    model.rotation.x = -Math.PI / 2
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
