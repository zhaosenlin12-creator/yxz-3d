<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import * as THREE from 'three'

type YXZStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing' | 'success'

const props = withDefaults(defineProps<{
  status?: YXZStatus
  paused?: boolean
}>(), {
  status: 'idle',
  paused: false,
})

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })
const canvasContainer = ref<HTMLDivElement>()
const activeLabel = computed(() => ({
  idle: '欢迎，我是宜小智',
  listening: '我在听，请告诉我',
  thinking: '正在思考…',
  speaking: '正在回应',
  processing: '正在处理，请稍候',
  success: '完成了，看看效果吧',
}[props.status]))

let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene | undefined
let camera: THREE.PerspectiveCamera | undefined
let character: THREE.Group | undefined
let head: THREE.Group | undefined
let leftArm: THREE.Group | undefined
let rightArm: THREE.Group | undefined
let mouth: THREE.Mesh | undefined
let leftEye: THREE.Mesh | undefined
let rightEye: THREE.Mesh | undefined
let animationFrame = 0
let resizeObserver: ResizeObserver | undefined
let motionQuery: MediaQueryList | undefined
let onMotionPreferenceChange: ((event: MediaQueryListEvent) => void) | undefined
let reducedMotion = false

const white = new THREE.MeshStandardMaterial({ color: 0xF6FBFF, roughness: 0.24, metalness: 0.08 })
const blue = new THREE.MeshStandardMaterial({ color: 0x159DE0, roughness: 0.2, metalness: 0.2, emissive: 0x063A5D, emissiveIntensity: 0.25 })
const dark = new THREE.MeshStandardMaterial({ color: 0x06182E, roughness: 0.14, metalness: 0.3, emissive: 0x03253F, emissiveIntensity: 0.5 })
const cyan = new THREE.MeshStandardMaterial({ color: 0x79EDFF, roughness: 0.12, metalness: 0.1, emissive: 0x16CFFF, emissiveIntensity: 1.5 })

function addMesh(parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: THREE.Material, position: [number, number, number], scale?: [number, number, number]) {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.set(...position)
  if (scale)
    mesh.scale.set(...scale)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

function addLimb(parent: THREE.Group, side: -1 | 1) {
  const pivot = new THREE.Group()
  pivot.position.set(side * 0.82, 1.55, 0)
  const upper = new THREE.Group()
  upper.rotation.z = side * -0.1
  addMesh(upper, new THREE.CapsuleGeometry(0.16, 0.46, 6, 12), white, [0, -0.32, 0], [1, 1, 0.9])
  addMesh(upper, new THREE.SphereGeometry(0.2, 18, 12), blue, [0, -0.63, 0])
  addMesh(upper, new THREE.CapsuleGeometry(0.14, 0.4, 6, 12), white, [0, -0.98, 0], [1, 1, 0.9])
  addMesh(upper, new THREE.SphereGeometry(0.2, 18, 12), white, [0, -1.28, 0.02], [1.15, 0.8, 0.9])
  pivot.add(upper)
  parent.add(pivot)
  return pivot
}

function buildCharacter() {
  const root = new THREE.Group()
  const torso = new THREE.Group()
  addMesh(torso, new THREE.CapsuleGeometry(0.58, 0.76, 8, 24), white, [0, 1.08, 0], [1, 1, 0.72])
  addMesh(torso, new THREE.BoxGeometry(0.5, 0.32, 0.05), blue, [0, 1.2, 0.47], [1, 1, 0.6])
  addMesh(torso, new THREE.BoxGeometry(0.18, 0.09, 0.03), cyan, [0, 1.2, 0.51])
  root.add(torso)

  const feet = new THREE.Group()
  for (const side of [-1, 1] as const) {
    const leg = new THREE.Group()
    leg.position.set(side * 0.32, 0.38, 0)
    addMesh(leg, new THREE.CapsuleGeometry(0.2, 0.54, 6, 14), white, [0, -0.2, 0], [1, 1, 0.82])
    addMesh(leg, new THREE.SphereGeometry(0.23, 18, 12), blue, [0, -0.6, 0])
    addMesh(leg, new THREE.BoxGeometry(0.43, 0.22, 0.58), white, [0, -0.82, 0.1], [1, 1, 0.9])
    addMesh(leg, new THREE.BoxGeometry(0.45, 0.08, 0.62), blue, [0, -0.91, 0.12])
    feet.add(leg)
  }
  root.add(feet)

  leftArm = addLimb(root, -1)
  rightArm = addLimb(root, 1)

  const wings = new THREE.Group()
  for (const side of [-1, 1] as const) {
    const wing = addMesh(wings, new THREE.ConeGeometry(0.42, 0.9, 4), white, [side * 0.72, 1.2, -0.45], [1, 0.8, 0.18])
    wing.rotation.z = side * Math.PI / 2
    wing.rotation.y = side * 0.15
  }
  root.add(wings)

  head = new THREE.Group()
  head.position.y = 2.35
  addMesh(head, new THREE.SphereGeometry(1.06, 32, 22), white, [0, 0, 0], [1.08, 0.9, 0.9])
  addMesh(head, new THREE.SphereGeometry(0.87, 32, 18), dark, [0, -0.02, 0.86], [1, 0.7, 0.16])
  leftEye = addMesh(head, new THREE.SphereGeometry(0.16, 18, 12), cyan, [-0.31, 0.08, 1.02], [1, 1.2, 0.6])
  rightEye = addMesh(head, new THREE.SphereGeometry(0.16, 18, 12), cyan, [0.31, 0.08, 1.02], [1, 1.2, 0.6])
  mouth = addMesh(head, new THREE.TorusGeometry(0.17, 0.035, 8, 24, Math.PI), cyan, [0, -0.27, 1.02], [1, 1, 0.4])
  mouth.rotation.z = Math.PI
  addMesh(head, new THREE.CylinderGeometry(0.08, 0.08, 0.3, 12), blue, [0, 1.13, 0], [1, 1, 1])
  addMesh(head, new THREE.SphereGeometry(0.13, 18, 12), cyan, [0, 1.31, 0])
  const halo = addMesh(head, new THREE.TorusGeometry(1.15, 0.065, 10, 48), cyan, [0, 1.22, 0], [1, 0.48, 1])
  halo.rotation.x = 0.12
  for (const side of [-1, 1] as const) {
    const ear = addMesh(head, new THREE.CylinderGeometry(0.2, 0.2, 0.12, 24), blue, [side * 1.01, 0.08, 0], [1, 1, 1])
    ear.rotation.z = Math.PI / 2
    addMesh(head, new THREE.CylinderGeometry(0.1, 0.1, 0.13, 24), cyan, [side * 1.08, 0.08, 0], [1, 1, 1])
  }
  root.add(head)
  return root
}

function resize() {
  if (!renderer || !camera || !canvasContainer.value)
    return
  const width = Math.max(1, canvasContainer.value.clientWidth)
  const height = Math.max(1, canvasContainer.value.clientHeight)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height, false)
}

function animate(now: number) {
  if (!renderer || !scene || !camera || !character)
    return
  const seconds = now / 1000
  const still = props.paused || reducedMotion
  const phase = still ? 0 : seconds
  const speaking = props.status === 'speaking'
  character.position.y = Math.sin(phase * 1.7) * (props.status === 'success' ? 0.12 : 0.035)
  character.rotation.y = Math.sin(phase * 0.55) * 0.035
  if (head) {
    head.rotation.z = props.status === 'thinking' ? -0.09 + Math.sin(phase * 0.8) * 0.02 : Math.sin(phase * 0.7) * 0.018
    head.rotation.x = props.status === 'listening' ? -0.035 : 0
  }
  if (leftArm && rightArm) {
    leftArm.rotation.z = props.status === 'success' ? -0.58 : Math.sin(phase * 0.9) * 0.035
    rightArm.rotation.z = props.status === 'idle' || props.status === 'speaking' ? -0.28 + Math.sin(phase * 2) * 0.08 : 0.08
    if (props.status === 'listening')
      rightArm.rotation.z = -0.12
  }
  if (mouth) {
    mouth.scale.y = speaking ? 0.65 + (Math.sin(phase * 12) + 1) * 0.12 : 1
    mouth.scale.x = speaking ? 1.1 : 1
  }
  if (leftEye && rightEye) {
    const blink = !still && Math.sin(seconds * 0.73) > 0.995 ? 0.12 : 1
    leftEye.scale.y = blink * (props.status === 'thinking' ? 0.85 : 1)
    rightEye.scale.y = blink * (props.status === 'thinking' ? 0.85 : 1)
  }
  renderer.render(scene, camera)
  animationFrame = requestAnimationFrame(animate)
}

onMounted(() => {
  if (!canvasContainer.value)
    return
  componentState.value = 'loading'
  try {
    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(28, 1, 0.1, 100)
    camera.position.set(0, 1.35, 9.6)
    camera.lookAt(0, 1.08, 0)
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    canvasContainer.value.appendChild(renderer.domElement)
    scene.add(new THREE.HemisphereLight(0xE9F9FF, 0x274A63, 1.8))
    const key = new THREE.DirectionalLight(0xFFFFFF, 3.2)
    key.position.set(3, 6, 5)
    key.castShadow = true
    scene.add(key)
    const rim = new THREE.PointLight(0x18B8EF, 2.2, 8)
    rim.position.set(-3, 2.5, 2)
    scene.add(rim)
    character = buildCharacter()
    character.scale.setScalar(0.8)
    scene.add(character)
    motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion = motionQuery.matches
    onMotionPreferenceChange = (event) => { reducedMotion = event.matches }
    motionQuery.addEventListener('change', onMotionPreferenceChange)
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvasContainer.value)
    resize()
    componentState.value = 'mounted'
    animationFrame = requestAnimationFrame(animate)
  }
  catch (error) {
    componentState.value = 'pending'
    console.error('Failed to initialize 宜小智 3D scene', error)
  }
})

watch(() => props.paused, () => resize())

onUnmounted(() => {
  cancelAnimationFrame(animationFrame)
  resizeObserver?.disconnect()
  if (motionQuery && onMotionPreferenceChange)
    motionQuery.removeEventListener('change', onMotionPreferenceChange)
  renderer?.dispose()
  renderer?.domElement.remove()
  scene?.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose()
      if (Array.isArray(object.material))
        object.material.forEach(material => material.dispose())
      else
        object.material.dispose()
    }
  })
})
</script>

<template>
  <div class="yxz-procedural-scene" aria-label="宜小智动态 3D 形象">
    <div class="yxz-procedural-bubble" role="status" aria-live="polite">
      <span class="yxz-procedural-dot" />
      <span>{{ activeLabel }}</span>
    </div>
    <div ref="canvasContainer" class="yxz-procedural-canvas" />
  </div>
</template>

<style scoped>
.yxz-procedural-scene {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.yxz-procedural-canvas {
  width: 100%;
  height: 100%;
}

.yxz-procedural-canvas :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}

.yxz-procedural-bubble {
  position: absolute;
  top: 4%;
  left: 50%;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: .5rem;
  max-width: calc(100% - 2rem);
  padding: .5rem .85rem;
  border: 1px solid rgba(27, 111, 177, .22);
  border-radius: .7rem;
  background: rgba(255, 255, 255, .9);
  color: #15547c;
  box-shadow: 0 6px 20px rgba(27, 111, 177, .12);
  font-size: .82rem;
  transform: translateX(-50%);
  white-space: nowrap;
}

.yxz-procedural-dot {
  width: .5rem;
  height: .5rem;
  border-radius: 50%;
  background: #18a8e0;
  box-shadow: 0 0 0 4px rgba(24, 168, 224, .12);
}
</style>
