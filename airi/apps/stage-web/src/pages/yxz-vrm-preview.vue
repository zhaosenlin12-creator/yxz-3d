<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import YXZRealModelScene from '../../../../packages/stage-ui-three/src/components/YXZRealModelScene.vue'

const route = useRoute()
const sessionId = String(route.query.session ?? '')
const mounted = ref(false)
const loadingProgress = ref(0)
const loadingPhase = ref<'download' | 'parse' | 'shader' | 'anim' | 'ready'>('download')

const phaseLabels = {
  download: '下载宜小智 3D 模型',
  parse: '解析 VRM 骨骼结构',
  shader: '编译实时着色器',
  anim: '初始化动画系统',
  ready: '加载完成'
}

onMounted(() => {
  // 模拟加载进度（实际加载由YXZRealModelScene内部完成）
  const stages = [
    { phase: 'download', duration: 500, progress: 40 },
    { phase: 'parse', duration: 300, progress: 60 },
    { phase: 'shader', duration: 200, progress: 80 },
    { phase: 'anim', duration: 200, progress: 100 }
  ]

  let currentProgress = 0
  stages.forEach((stage, index) => {
    setTimeout(() => {
      loadingPhase.value = stage.phase as any
      const interval = setInterval(() => {
        if (currentProgress < stage.progress) {
          currentProgress += 2
          loadingProgress.value = Math.min(currentProgress, stage.progress)
        } else {
          clearInterval(interval)
        }
      }, stage.duration / 20)
    }, stages.slice(0, index).reduce((sum, s) => sum + s.duration, 0))
  })

  window.setTimeout(() => {
    mounted.value = true
    loadingPhase.value = 'ready'
  }, 1400)
})

const origin = typeof window !== 'undefined' ? window.location.origin : ''
function goBack() {
  if (typeof window !== 'undefined')
    window.close()
}
</script>

<template>
  <div class="yxz-vrm-preview">
    <header class="yxz-vrm-header">
      <div class="yxz-vrm-title">
        <strong>宜小智 · 3D 精致模型</strong>
        <small>主项目同款形象 · 白色宇航服 · 胸前 YCSL 标识 · 会自然呼吸的轻动作</small>
      </div>
      <div class="yxz-vrm-actions">
        <a v-if="sessionId" class="yxz-vrm-btn" :href="`/yxz-studio?session=${encodeURIComponent(sessionId)}`" target="_blank" rel="noopener noreferrer">
          去创作面板继续编辑 ↗
        </a>
        <a class="yxz-vrm-btn" :href="origin" @click.prevent="goBack">← 返回对话</a>
      </div>
    </header>

    <main class="yxz-vrm-stage">
      <YXZRealModelScene
        status="idle"
        :speaking-level="0"
        :paused="false"
        class="yxz-vrm-scene"
      />

      <!-- 增强的加载状态 -->
      <div v-if="!mounted" class="yxz-loading-enhanced">
        <div class="loading-spinner"></div>
        <div class="loading-phase">{{ phaseLabels[loadingPhase] }}</div>
        <div class="loading-progress-bar">
          <div class="loading-progress-fill" :style="{ width: `${loadingProgress}%` }"></div>
        </div>
        <div class="loading-percent">{{ Math.round(loadingProgress) }}%</div>
        <div class="loading-tips">
          <p v-if="loadingPhase === 'download'">💡 首次加载需要下载高精度 3D 模型</p>
          <p v-if="loadingPhase === 'shader'">✨ 正在编译实时光影效果</p>
          <p v-if="loadingProgress > 60 && !mounted">⏳ 马上就好，请稍候…</p>
        </div>
      </div>
    </main>

    <footer class="yxz-vrm-footer">
      <span>✨ 预制精致模型：选择后可直接展示成品，或描述需求让宜小智为你定制新模型去打印/切割</span>
    </footer>
  </div>
</template>

<style scoped>
.yxz-vrm-preview {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(1100px 650px at 50% -12%, rgba(56, 182, 255, .18) 0%, transparent 58%),
    linear-gradient(160deg, #061527 0%, #0b2a4a 48%, #071a30 100%);
  color: #eaf6ff;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  overflow: hidden;
}

.yxz-vrm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding: 18px 26px 10px;
}

.yxz-vrm-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.yxz-vrm-title strong {
  font-size: 20px;
  letter-spacing: .03em;
}

.yxz-vrm-title small {
  color: #bcd9f2;
  font-size: 12.5px;
}

.yxz-vrm-actions {
  display: flex;
  gap: 10px;
}

.yxz-vrm-btn {
  border: 1px solid rgba(160, 205, 255, .45);
  border-radius: 8px;
  background: rgba(255, 255, 255, .07);
  color: #d9ecff;
  padding: 8px 14px;
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
}

.yxz-vrm-btn:hover {
  background: rgba(255, 255, 255, .14);
}

.yxz-vrm-stage {
  position: relative;
  flex: 1;
  min-height: 560px;
  margin: 4px 22px 10px;
  border: 1px solid rgba(160, 205, 255, .28);
  border-radius: 16px;
  overflow: hidden;
  background: rgba(255, 255, 255, .03);
}

.yxz-vrm-scene {
  position: absolute;
  inset: 0;
}

/* 增强的加载状态样式 */
.yxz-loading-enhanced {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: rgba(6, 21, 39, 0.85);
  backdrop-filter: blur(8px);
  color: #9fc6e6;
  z-index: 10;
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
  font-variant-numeric: tabular-nums;
}

.loading-tips {
  margin-top: 8px;
  text-align: center;
  font-size: 12.5px;
  color: #7fa9cc;
  max-width: 320px;
}

.loading-tips p {
  margin: 4px 0;
}

.yxz-vrm-footer {
  padding: 4px 26px 18px;
  color: #7fa9cc;
  font-size: 12.5px;
}
</style>
