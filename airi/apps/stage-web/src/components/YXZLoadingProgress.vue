<script setup lang="ts">
import { ref, computed } from 'vue'

interface LoadingPhase {
  phase: 'download' | 'parse' | 'shader' | 'anim' | 'ready'
  progress: number
  message: string
}

const props = withDefaults(defineProps<{
  phase?: LoadingPhase['phase']
  progress?: number
}>(), {
  phase: 'download',
  progress: 0
})

const phaseLabels = {
  download: '下载宜小智 3D 模型',
  parse: '解析 VRM 骨骼结构',
  shader: '编译实时着色器',
  anim: '初始化动画系统',
  ready: '加载完成'
}

const message = computed(() => phaseLabels[props.phase])

const tips = computed(() => {
  if (props.phase === 'download') return '💡 首次加载需要下载高精度 3D 模型'
  if (props.phase === 'shader') return '✨ 正在编译实时光影效果'
  if (props.progress > 50 && props.phase !== 'ready') return '⏳ 马上就好，请稍候…'
  return ''
})
</script>

<template>
  <div class="yxz-loading-progress">
    <div class="loading-spinner"></div>
    <div class="loading-phase">{{ message }}</div>
    <div class="loading-progress-bar">
      <div class="loading-progress-fill" :style="{ width: `${progress}%` }"></div>
    </div>
    <div class="loading-percent">{{ Math.round(progress) }}%</div>
    <div v-if="tips" class="loading-tips">{{ tips }}</div>
  </div>
</template>

<style scoped>
.yxz-loading-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #9fc6e6;
}

.loading-spinner {
  width: 48px;
  height: 48px;
  border: 4px solid rgba(160, 205, 255, 0.15);
  border-top-color: #38BDF8;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-phase {
  font-size: 15px;
  font-weight: 500;
  color: #d9ecff;
}

.loading-progress-bar {
  width: 280px;
  height: 6px;
  background: rgba(160, 205, 255, 0.12);
  border-radius: 3px;
  overflow: hidden;
}

.loading-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #38BDF8 0%, #22D3EE 100%);
  transition: width 0.3s ease;
}

.loading-percent {
  font-size: 13px;
  color: #7fa9cc;
}

.loading-tips {
  margin-top: 8px;
  font-size: 12.5px;
  color: #7fa9cc;
  text-align: center;
}
</style>
