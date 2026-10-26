<script setup lang="ts">
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'
import { computed, onMounted, onUnmounted, ref } from 'vue'

import * as THREE from 'three'

type YXZStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing' | 'success'

const props = withDefaults(defineProps<{
  status?: YXZStatus
  speakingLevel?: number
  paused?: boolean
}>(), {
  status: 'idle',
  speakingLevel: 0,
  paused: false,
})

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })
const canvasContainer = ref<HTMLDivElement>()
const activeLabel = computed(() => ({
  idle: '你好，我是宜小智，想做什么？',
  listening: '我在认真听你的想法',
  thinking: '我正在理解和整理方案',
  speaking: '我来向你介绍这份方案',
  processing: '我正在生成预览和 3D 模型',
  success: '方案完成，可以继续编辑或下载',
}[props.status]))

let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene | undefined
let camera: THREE.PerspectiveCamera | undefined
let actor: THREE.Group | undefined
let head: THREE.Group | undefined
let jaw: THREE.Group | undefined
let leftArm: THREE.Group | undefined
let rightArm: THREE.Group | undefined
let rightForearm: THREE.Group | undefined
let rightWrist: THREE.Group | undefined
let eyeL: THREE.Object3D | undefined
let eyeR: THREE.Object3D | undefined
let pupilL: THREE.Object3D | undefined
let pupilR: THREE.Object3D | undefined
let mouthCavity: THREE.Object3D | undefined
let smileLine: THREE.Object3D | undefined
let halo: THREE.Object3D | undefined
let faceGlow: THREE.PointLight | undefined
let animationFrame = 0
let resizeObserver: ResizeObserver | undefined
let motionQuery: MediaQueryList | undefined
let motionListener: ((event: MediaQueryListEvent) => void) | undefined
let reducedMotion = false
let lastFrameAt = 0
let mouthEnvelope = 0
let blinkStartedAt = -Infinity
let nextBlinkAt = 3.2
let lastBounds: THREE.Vector3 | undefined

const white = new THREE.MeshPhysicalMaterial({ color: 0xF5F8FF, roughness: 0.24, metalness: 0.03, clearcoat: 0.48, clearcoatRoughness: 0.2 })
const whiteSoft = new THREE.MeshPhysicalMaterial({ color: 0xE9F1FB, roughness: 0.3, metalness: 0.02, clearcoat: 0.35 })
const blue = new THREE.MeshPhysicalMaterial({ color: 0x087FE2, roughness: 0.22, metalness: 0.32, clearcoat: 0.34, emissive: 0x03295B, emissiveIntensity: 0.22 })
const navy = new THREE.MeshPhysicalMaterial({ color: 0x061A3C, roughness: 0.13, metalness: 0.26, clearcoat: 0.76, clearcoatRoughness: 0.12, emissive: 0x021C3C, emissiveIntensity: 0.3 })
const joint = new THREE.MeshPhysicalMaterial({ color: 0x1A2B3D, roughness: 0.32, metalness: 0.68 })
const cyan = new THREE.MeshPhysicalMaterial({ color: 0x75EDFF, roughness: 0.12, metalness: 0.06, emissive: 0x0BCFFF, emissiveIntensity: 2.1, transparent: true, opacity: 0.94 })
const eyeWhite = new THREE.MeshPhysicalMaterial({ color: 0xE9FFFF, roughness: 0.16, metalness: 0.05, emissive: 0x50EAFF, emissiveIntensity: 1.7 })
const pupil = new THREE.MeshPhysicalMaterial({ color: 0x063B75, roughness: 0.18, metalness: 0.24, emissive: 0x02192E, emissiveIntensity: 0.35 })
const mouthDark = new THREE.MeshPhysicalMaterial({ color: 0x220C1A, roughness: 0.25, metalness: 0.02, emissive: 0x170008, emissiveIntensity: 0.2 })

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

function addRounded(parent: THREE.Object3D, size: [number, number, number], position: [number, number, number], material: THREE.Material, radius = 0.08) {
  return addMesh(parent, new RoundedBoxGeometry(...size, radius, 4), material, position)
}

function createWingGeometry() {
  const shape = new THREE.Shape()
  shape.moveTo(0, 0)
  shape.quadraticCurveTo(0.3, 0.06, 0.88, 0.32)
  shape.quadraticCurveTo(0.72, 0.04, 0.98, -0.1)
  shape.quadraticCurveTo(0.45, -0.22, 0, -0.12)
  shape.closePath()
  return new THREE.ExtrudeGeometry(shape, { depth: 0.08, bevelEnabled: true, bevelSize: 0.025, bevelThickness: 0.025, bevelSegments: 2 })
}

function createStarGeometry() {
  const shape = new THREE.Shape()
  for (let i = 0; i < 10; i++) {
    const radius = i % 2 === 0 ? 0.26 : 0.11
    const angle = -Math.PI / 2 + i * Math.PI / 5
    const x = Math.cos(angle) * radius
    const y = Math.sin(angle) * radius
    if (i === 0)
      shape.moveTo(x, y)
    else
      shape.lineTo(x, y)
  }
  shape.closePath()
  return new THREE.ExtrudeGeometry(shape, { depth: 0.05, bevelEnabled: true, bevelSize: 0.02, bevelThickness: 0.02, bevelSegments: 2 })
}

function addLimb(parent: THREE.Group, side: -1 | 1, waveable: boolean) {
  const shoulder = new THREE.Group()
  shoulder.position.set(side * 0.82, 1.86, 0)
  const upper = new THREE.Group()
  upper.rotation.z = side * -0.08
  addMesh(upper, new THREE.SphereGeometry(0.235, 28, 18), whiteSoft, [0, 0, 0], [1, 0.72, 0.88])
  addMesh(upper, new THREE.CapsuleGeometry(0.18, 0.42, 8, 20), white, [0, -0.34, 0], [1, 1, 0.9])
  addMesh(upper, new THREE.TorusGeometry(0.19, 0.045, 10, 24), joint, [0, -0.61, 0], [1, 1, 0.9])
  const forearm = new THREE.Group()
  forearm.position.y = -0.64
  addMesh(forearm, new THREE.CapsuleGeometry(0.16, 0.42, 8, 20), white, [0, -0.32, 0], [1, 1, 0.9])
  addMesh(forearm, new THREE.TorusGeometry(0.17, 0.045, 10, 24), blue, [0, -0.57, 0], [1, 1, 0.9])
  const wrist = new THREE.Group()
  wrist.position.y = -0.6
  addMesh(wrist, new THREE.SphereGeometry(0.21, 24, 16), whiteSoft, [0, -0.12, 0], [1.1, 0.84, 0.95])
  for (let finger = 0; finger < 5; finger++) {
    const angle = (finger - 2) * 0.26
    addMesh(wrist, new THREE.CapsuleGeometry(0.055, 0.2, 5, 10), white, [Math.sin(angle) * 0.14, -0.25 - Math.abs(angle) * 0.03, 0.035], [0.9, 1, 0.9]).rotation.z = angle * 0.55
  }
  forearm.add(wrist)
  upper.add(forearm)
  shoulder.add(upper)
  parent.add(shoulder)
  if (waveable) {
    rightForearm = forearm
    rightWrist = wrist
  }
  return shoulder
}

function buildCharacter() {
  const root = new THREE.Group()
  const torso = new THREE.Group()
  torso.name = 'TorsoRigid'
  addRounded(torso, [1.28, 1.08, 0.78], [0, 1.15, 0], white, 0.25)
  addRounded(torso, [0.72, 0.22, 0.08], [0, 1.56, 0.42], blue, 0.06)
  addRounded(torso, [0.42, 0.07, 0.05], [0, 1.22, 0.45], cyan, 0.025)
  addRounded(torso, [0.34, 0.18, 0.08], [0, 1.78, 0.38], joint, 0.05)
  root.add(torso)

  for (const side of [-1, 1] as const) {
    const leg = new THREE.Group()
    leg.name = side < 0 ? 'LegL' : 'LegR'
    leg.position.set(side * 0.34, 0.76, 0)
    addMesh(leg, new THREE.CapsuleGeometry(0.25, 0.52, 8, 22), white, [0, -0.28, 0], [1, 1, 0.88])
    addRounded(leg, [0.46, 0.3, 0.22], [0, -0.66, 0.04], blue, 0.1)
    addMesh(leg, new THREE.CapsuleGeometry(0.2, 0.48, 8, 22), whiteSoft, [0, -0.98, 0], [1, 1, 0.88])
    addRounded(leg, [0.58, 0.3, 0.78], [0, -1.35, 0.1], white, 0.14)
    addRounded(leg, [0.62, 0.13, 0.8], [0, -1.53, 0.16], blue, 0.06)
    addMesh(leg, new THREE.TorusGeometry(0.11, 0.035, 8, 24), cyan, [side * -0.16, -1.22, 0.48], [1, 1, 0.5])
    root.add(leg)
  }

  leftArm = addLimb(root, -1, false)
  rightArm = addLimb(root, 1, true)
  leftArm.rotation.z = 0.14
  rightArm.rotation.z = -0.28

  const wings = new THREE.Group()
  for (const side of [-1, 1] as const) {
    for (let feather = 0; feather < 3; feather++) {
      const wing = addMesh(wings, createWingGeometry(), whiteSoft, [side * (0.57 + feather * 0.03), 1.5 - feather * 0.14, -0.38 - feather * 0.035])
      wing.scale.x = side
      wing.rotation.y = side * (0.18 + feather * 0.04)
      wing.rotation.z = side * (0.05 + feather * 0.12)
      addMesh(wing, new THREE.BoxGeometry(0.58, 0.018, 0.018), cyan, [0.48, 0.03, 0.05], [side, 1, 1])
    }
  }
  root.add(wings)

  const book = new THREE.Group()
  book.name = 'Book'
  book.position.set(-0.68, 1.06, 0.28)
  book.rotation.z = -0.12
  addRounded(book, [0.28, 0.7, 0.12], [0, 0, 0], blue, 0.04)
  addRounded(book, [0.21, 0.61, 0.055], [0, 0, 0.075], white, 0.025)
  addRounded(book, [0.08, 0.55, 0.02], [0.07, 0, 0.108], whiteSoft, 0.01)
  root.add(book)

  head = new THREE.Group()
  head.name = 'HeadPivot'
  head.position.y = 2.55
  addMesh(head, new THREE.SphereGeometry(1.08, 48, 32), white, [0, 0, 0], [1.12, 1, 0.92])
  addMesh(head, new THREE.SphereGeometry(0.92, 48, 28), navy, [0, -0.02, 0.82], [1, 0.68, 0.22])
  const visorHighlight = addMesh(head, new THREE.SphereGeometry(0.88, 48, 24), cyan, [0, 0.16, 0.88], [1, 0.05, 0.012])
  visorHighlight.material.transparent = true
  visorHighlight.material.opacity = 0.23
  eyeL = addMesh(head, new THREE.SphereGeometry(0.19, 28, 20), eyeWhite, [-0.33, 0.02, 1.03], [0.88, 1.25, 0.25])
  eyeR = addMesh(head, new THREE.SphereGeometry(0.19, 28, 20), eyeWhite, [0.33, 0.02, 1.03], [0.88, 1.25, 0.25])
  pupilL = addMesh(head, new THREE.SphereGeometry(0.07, 20, 14), pupil, [-0.33, 0.02, 1.105], [1, 1.2, 0.32])
  pupilR = addMesh(head, new THREE.SphereGeometry(0.07, 20, 14), pupil, [0.33, 0.02, 1.105], [1, 1.2, 0.32])

  jaw = new THREE.Group()
  jaw.name = 'JawPivot'
  jaw.position.set(0, -0.28, 0.86)
  addMesh(jaw, new THREE.SphereGeometry(0.77, 40, 24), whiteSoft, [0, 0, 0.05], [1, 0.52, 0.18])
  mouthCavity = addRounded(jaw, [0.38, 0.1, 0.045], [0, -0.08, 0.21], mouthDark, 0.04)
  mouthCavity.visible = false
  smileLine = addMesh(jaw, new THREE.TorusGeometry(0.18, 0.03, 10, 32, Math.PI), mouthDark, [0, 0.02, 0.225], [1, 1, 0.6])
  smileLine.rotation.z = Math.PI
  jaw.add(mouthCavity)
  jaw.add(smileLine)
  head.add(jaw)

  for (const side of [-1, 1] as const) {
    const ear = new THREE.Group()
    ear.name = side < 0 ? 'EarL' : 'EarR'
    ear.position.set(side * 1.07, 0.02, 0)
    ear.rotation.z = Math.PI / 2
    addMesh(ear, new THREE.CylinderGeometry(0.27, 0.27, 0.16, 32), blue, [0, 0, 0])
    addMesh(ear, new THREE.CylinderGeometry(0.17, 0.17, 0.18, 32), cyan, [0, 0, 0.01])
    head.add(ear)
  }

  halo = addMesh(head, new THREE.TorusGeometry(1.2, 0.065, 14, 64), cyan, [0, 1.15, 0], [1, 0.5, 1])
  halo.rotation.x = 0.06
  const star = addMesh(head, createStarGeometry(), blue, [0.93, 1.2, 0.02], [0.62, 0.62, 0.62])
  star.rotation.z = -0.18
  addRounded(head, [0.35, 0.11, 0.24], [0, 1.03, -0.05], blue, 0.04)
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

function fitCharacter() {
  if (!actor || !camera)
    return
  const bounds = new THREE.Box3().setFromObject(actor)
  const size = bounds.getSize(new THREE.Vector3())
  const center = bounds.getCenter(new THREE.Vector3())
  const targetHeight = 3.2
  actor.scale.setScalar(targetHeight / Math.max(size.y, 0.001))
  actor.position.set(-center.x * actor.scale.x, -Math.min(bounds.min.y * actor.scale.y - 0.28, 0), -center.z * actor.scale.z)
  lastBounds = size.multiplyScalar(actor.scale.x)
}

function animate(now: number) {
  if (!renderer || !scene || !camera || !actor || !head || !jaw)
    return
  const seconds = now / 1000
  const still = props.paused
  const motionScale = reducedMotion ? 0.75 : 1
  const phase = still ? 0 : seconds
  const delta = lastFrameAt > 0 ? Math.min((now - lastFrameAt) / 1000, 0.1) : 0
  lastFrameAt = now
  const headTargetZ = props.status === 'thinking' ? -0.075 : props.status === 'listening' ? 0.045 : Math.sin(phase * 0.45) * 0.018
  const headTargetX = props.status === 'listening' ? -0.035 : props.status === 'thinking' ? 0.018 : 0
  head.rotation.z = THREE.MathUtils.damp(head.rotation.z, headTargetZ, 7, delta)
  head.rotation.x = THREE.MathUtils.damp(head.rotation.x, headTargetX, 7, delta)
  if (leftArm)
    leftArm.rotation.z = THREE.MathUtils.damp(leftArm.rotation.z, 0.14, 8, delta)
  if (rightArm) {
    const wave = props.status === 'success' ? Math.sin(phase * 3.2) * 0.16 : props.status === 'speaking' ? Math.sin(phase * 1.6) * 0.035 : Math.sin(phase * 0.75) * 0.018
    rightArm.rotation.z = THREE.MathUtils.damp(rightArm.rotation.z, -0.28 + wave, 8, delta)
  }
  if (rightForearm)
    rightForearm.rotation.z = THREE.MathUtils.damp(rightForearm.rotation.z, props.status === 'success' ? Math.sin(phase * 3.2) * 0.13 : 0, 9, delta)
  if (rightWrist)
    rightWrist.rotation.z = THREE.MathUtils.damp(rightWrist.rotation.z, props.status === 'success' ? Math.sin(phase * 3.2 + 0.45) * 0.2 : 0, 10, delta)
  if (halo)
    halo.rotation.z = THREE.MathUtils.damp(halo.rotation.z, props.status === 'thinking' ? -0.035 : 0, 6, delta)

  if (!still && seconds >= nextBlinkAt) {
    blinkStartedAt = seconds
    nextBlinkAt = seconds + (reducedMotion ? 5.5 : 3.2) + Math.random() * (reducedMotion ? 2 : 3.2)
  }
  const blinkAge = seconds - blinkStartedAt
  const blink = still || blinkAge < 0 ? 0 : blinkAge < 0.08 ? THREE.MathUtils.smoothstep(blinkAge, 0, 0.08) : blinkAge < 0.2 ? 1 - THREE.MathUtils.smoothstep(blinkAge, 0.08, 0.2) : 0
  for (const eye of [eyeL, eyeR, pupilL, pupilR]) {
    if (eye)
      eye.scale.y = THREE.MathUtils.damp(eye.scale.y, Math.max(0.05, 1 - blink), 28, delta)
  }
  const gaze = still ? 0 : props.status === 'thinking' ? Math.sin(phase * 0.72) * 0.018 : props.status === 'listening' ? Math.sin(phase * 0.9) * 0.01 : Math.sin(phase * 0.3) * 0.004
  if (pupilL)
    pupilL.position.x = THREE.MathUtils.damp(pupilL.position.x, -0.33 + gaze, 8, delta)
  if (pupilR)
    pupilR.position.x = THREE.MathUtils.damp(pupilR.position.x, 0.33 + gaze, 8, delta)

  const targetMouth = props.status === 'speaking' && !still ? THREE.MathUtils.clamp((props.speakingLevel || (0.2 + Math.max(0, Math.sin(phase * 7)) * 0.3)) * motionScale, 0, 1) : 0
  mouthEnvelope = THREE.MathUtils.damp(mouthEnvelope, targetMouth, 18, delta)
  const mouthOpen = mouthEnvelope > 0.12
  jaw.rotation.x = THREE.MathUtils.damp(jaw.rotation.x, -mouthEnvelope * 0.18, 12, delta)
  jaw.position.y = THREE.MathUtils.damp(jaw.position.y, -0.28 - mouthEnvelope * 0.035, 12, delta)
  if (mouthCavity)
    mouthCavity.visible = mouthOpen
  if (smileLine)
    smileLine.visible = !mouthOpen
  if (faceGlow) {
    faceGlow.intensity = (props.status === 'speaking' ? 1.45 : props.status === 'success' ? 1.7 : 0.82) + Math.sin(phase * 2.4) * 0.08
    faceGlow.color.set(props.status === 'thinking' ? 0x7C9BFF : props.status === 'success' ? 0x54E6A8 : 0x39D8FF)
  }
  // A lightweight integrity check catches accidental whole-model transforms.
  if (lastBounds && actor.scale.x > 0 && actor.scale.x < 10) {
    const current = new THREE.Box3().setFromObject(actor).getSize(new THREE.Vector3())
    if (current.y > lastBounds.y * 1.08 || current.y < lastBounds.y * 0.92)
      console.warn('宜小智原始模型形体保护：检测到异常高度变化')
  }
  renderer.render(scene, camera)
  animationFrame = requestAnimationFrame(animate)
}

onMounted(() => {
  if (!canvasContainer.value)
    return
  componentState.value = 'loading'
  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(28, 1, 0.1, 100)
  camera.position.set(0, 1.75, 8.6)
  camera.lookAt(0, 1.72, 0)
  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.08
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  canvasContainer.value.appendChild(renderer.domElement)
  scene.add(new THREE.HemisphereLight(0xE8F8FF, 0x18314B, 1.75))
  const key = new THREE.DirectionalLight(0xFFFFFF, 3.3)
  key.position.set(3, 5, 5)
  key.castShadow = true
  key.shadow.mapSize.set(1024, 1024)
  scene.add(key)
  const rim = new THREE.PointLight(0x16C9FF, 2.8, 8)
  rim.position.set(-3, 2.6, 2.5)
  scene.add(rim)
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1.55, 64), new THREE.ShadowMaterial({ color: 0x0B4261, opacity: 0.16 }))
  floor.rotation.x = -Math.PI / 2
  floor.position.y = 0.28
  floor.receiveShadow = true
  scene.add(floor)
  actor = buildCharacter()
  scene.add(actor)
  faceGlow = new THREE.PointLight(0x39D8FF, 0.8, 2.8)
  faceGlow.position.set(0, 2.55, 1.55)
  actor.add(faceGlow)
  fitCharacter()
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion = motionQuery.matches
  motionListener = (event) => {
    reducedMotion = event.matches
  }
  motionQuery.addEventListener('change', motionListener)
  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(canvasContainer.value)
  resize()
  componentState.value = 'mounted'
  animationFrame = requestAnimationFrame(animate)
})

onUnmounted(() => {
  cancelAnimationFrame(animationFrame)
  resizeObserver?.disconnect()
  if (motionQuery && motionListener)
    motionQuery.removeEventListener('change', motionListener)
  renderer?.dispose()
  renderer?.domElement.remove()
  const disposedMaterials = new Set<THREE.Material>()
  scene?.traverse((object) => {
    if (!(object instanceof THREE.Mesh))
      return
    object.geometry.dispose()
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials) {
      if (!disposedMaterials.has(material)) {
        disposedMaterials.add(material)
        material.dispose()
      }
    }
  })
})
</script>

<template>
  <div class="yxz-original-model-scene" :data-status="props.status" aria-label="宜小智原始动态 3D 形象">
    <div class="yxz-original-model-bubble" role="status" aria-live="polite">
      <span class="yxz-original-model-dot" />
      <span>{{ activeLabel }}</span>
      <span v-if="props.status === 'speaking' || props.status === 'thinking' || props.status === 'processing'" class="yxz-original-model-voice-dots" aria-hidden="true">
        <i v-for="index in 3" :key="index" :style="{ animationDelay: `${(index - 1) * 0.12}s` }" />
      </span>
    </div>
    <div ref="canvasContainer" class="yxz-original-model-canvas" />
  </div>
</template>

<style scoped>
.yxz-original-model-scene { position: relative; width: 100%; height: 100%; overflow: hidden; }
.yxz-original-model-canvas, .yxz-original-model-canvas :deep(canvas) { width: 100%; height: 100%; }
.yxz-original-model-canvas :deep(canvas) { display: block; }
.yxz-original-model-bubble { position: absolute; top: 4%; left: 50%; z-index: 2; display: flex; align-items: center; gap: .5rem; max-width: calc(100% - 2rem); padding: .5rem .85rem; border: 1px solid rgba(27,111,177,.22); border-radius: .7rem; background: rgba(255,255,255,.9); color: #15547c; box-shadow: 0 6px 20px rgba(27,111,177,.12); font-size: .82rem; transform: translateX(-50%); white-space: nowrap; }
.yxz-original-model-dot { width: .5rem; height: .5rem; border-radius: 50%; background: #18a8e0; box-shadow: 0 0 0 4px rgba(24,168,224,.12); }
.yxz-original-model-scene[data-status="thinking"] .yxz-original-model-dot, .yxz-original-model-scene[data-status="processing"] .yxz-original-model-dot { background: #7c72ff; box-shadow: 0 0 0 4px rgba(124,114,255,.14); }
.yxz-original-model-scene[data-status="speaking"] .yxz-original-model-dot { background: #18b8a4; box-shadow: 0 0 0 4px rgba(24,184,164,.14); }
.yxz-original-model-scene[data-status="success"] .yxz-original-model-dot { background: #2bb673; box-shadow: 0 0 0 4px rgba(43,182,115,.14); }
.yxz-original-model-voice-dots { display: inline-flex; align-items: center; gap: .18rem; height: 1rem; margin-left: .15rem; }
.yxz-original-model-voice-dots i { width: .18rem; height: .38rem; border-radius: 999px; background: #18a8e0; animation: yxz-original-voice-dot .7s ease-in-out infinite alternate; }
@keyframes yxz-original-voice-dot { from { transform: scaleY(.55); opacity: .52; } to { transform: scaleY(1.35); opacity: 1; } }
</style>
