<script setup lang="ts">
import type { YXZPoseId } from '../../assets/yxz'
import type { YXZInteractionStatus } from '../../assets/yxz/interaction'

import { computed } from 'vue'

import { getYXZPose } from '../../assets/yxz'
import { getYXZInteractionPresentation } from '../../assets/yxz/interaction'

const props = withDefaults(defineProps<{
  modelSrc?: string
  pose?: YXZPoseId
  status?: YXZInteractionStatus
  statusText?: string
  paused?: boolean
  xOffset?: number | string
  yOffset?: number | string
  scale?: number
}>(), {
  paused: false,
  scale: 1,
})

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })
const activeStatus = computed(() => props.status ?? 'idle')
const activePresentation = computed(() => getYXZInteractionPresentation(activeStatus.value))
const motionClass = computed(() => `yxz-motion-${activeStatus.value}`)
const resolvedModelSrc = computed(() => {
  if (props.status || props.pose)
    return getYXZPose(props.pose ?? activePresentation.value.pose).image

  return props.modelSrc ?? getYXZPose('frontWave').image
})

function onLoad() {
  componentState.value = 'mounted'
}

function onError() {
  componentState.value = 'pending'
}

function cssLength(value?: number | string) {
  if (value === undefined)
    return undefined

  return typeof value === 'number' ? `${value}px` : value
}
</script>

<template>
  <div
    relative h-full w-full overflow-hidden
    aria-label="宜小智互动形象"
  >
    <div
      role="status"
      aria-live="polite"
      absolute left="50%" top="4%" z-10
      max-w="calc(100% - 2rem)"
      translate-x="-50%"
      whitespace-nowrap
      rounded-lg border="1 solid rgba(27, 111, 177, 0.22)"
      bg="white/90"
      px-4 py-2
      text-sm text="[#15547c]"
      shadow="[0_6px_20px_rgba(27,111,177,0.12)]"
      transition="all 300 ease-out"
    >
      <span mr-2 inline-block h-2 w-2 rounded-full bg="[#18a8e0]" align-middle />
      <span>{{ props.statusText ?? activePresentation.label }}</span>
    </div>
    <div
      absolute inset-0
      class="yxz-character-motion"
      :class="[motionClass, { 'is-paused': props.paused }]"
    >
      <img
        :key="resolvedModelSrc"
        :src="resolvedModelSrc"
        alt="宜小智"
        left="50%" top="50%"

        pointer-events-none absolute h-full max-h-full max-w-full w-full select-none object-contain
        :style="{
          transform: `translate(calc(-50% + ${cssLength(props.xOffset) ?? '0px'}), calc(-50% + ${cssLength(props.yOffset) ?? '0px'})) scale(${props.scale})`,
          opacity: props.paused ? 0.94 : 1,
        }"
        @load="onLoad"
        @error="onError"
      >
    </div>
  </div>
</template>

<style scoped>
.yxz-character-motion {
  transform-origin: 50% 82%;
  will-change: transform;
}

.yxz-character-motion.is-paused {
  animation-play-state: paused;
}

.yxz-motion-idle {
  animation: yxz-float 4.8s ease-in-out infinite;
}

.yxz-motion-listening {
  animation: yxz-listen 1.8s ease-in-out infinite;
}

.yxz-motion-thinking,
.yxz-motion-processing {
  animation: yxz-think 1.55s ease-in-out infinite;
}

.yxz-motion-speaking {
  animation: yxz-speak 1.05s ease-in-out infinite;
}

.yxz-motion-success {
  animation: yxz-success 720ms cubic-bezier(.2, .85, .3, 1) both;
}

@keyframes yxz-float {
  0%, 100% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(0, -6px, 0); }
}

@keyframes yxz-listen {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(0deg); }
  50% { transform: translate3d(3px, -2px, 0) rotate(1deg); }
}

@keyframes yxz-think {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(0, -3px, 0) scale(1.012); }
}

@keyframes yxz-speak {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(0, -7px, 0) scale(1.018); }
}

@keyframes yxz-success {
  0% { transform: translate3d(0, 8px, 0) scale(.97); opacity: .7; }
  60% { transform: translate3d(0, -7px, 0) scale(1.025); opacity: 1; }
  100% { transform: translate3d(0, 0, 0) scale(1); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .yxz-character-motion {
    animation: none;
  }
}
</style>
