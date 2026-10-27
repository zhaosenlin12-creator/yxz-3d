<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import YXZRealModelScene from '../../../../packages/stage-ui-three/src/components/YXZRealModelScene.vue'

const route = useRoute()
const sessionId = String(route.query.session ?? '')
const mounted = ref(false)

onMounted(() => {
  // Let the scene settle before marking it mounted (a frame with actual WebGL).
  window.setTimeout(() => {
    mounted.value = true
  }, 1200)
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
      <div v-if="!mounted" class="yxz-vrm-loading">正在加载宜小智 3D 模型…</div>
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

.yxz-vrm-loading {
  position: absolute;
  inset: 50% auto auto 50%;
  transform: translate(-50%, -50%);
  color: #9fc6e6;
  font-size: 14px;
}

.yxz-vrm-footer {
  padding: 4px 26px 18px;
  color: #7fa9cc;
  font-size: 12.5px;
}
</style>
