<script setup lang="ts">
import type { YXZStatus } from '@proj-airi/stage-ui-three'

import { YXZPetScene } from '@proj-airi/stage-ui/components/scenes'
import { ref } from 'vue'

// Focused harness for judging the YXZ avatar: every interaction state is one
// click away, and the live mount/error state is surfaced instead of failing
// silently inside the stage.
const STATUSES: YXZStatus[] = ['idle', 'listening', 'thinking', 'speaking', 'processing', 'success']
const STATUS_LABELS: Record<YXZStatus, string> = {
  idle: '待机',
  listening: '聆听',
  thinking: '思考',
  speaking: '说话',
  processing: '生成中',
  success: '完成',
}

const status = ref<YXZStatus>('idle')
const speakingLevel = ref(0)
const paused = ref(false)
const mountState = ref<'pending' | 'loading' | 'mounted'>('pending')
const loadError = ref('')

let speechTimer: ReturnType<typeof setInterval> | undefined

function toggleSpeech() {
  if (speechTimer) {
    clearInterval(speechTimer)
    speechTimer = undefined
    speakingLevel.value = 0
    return
  }
  // Drive the mouth from a synthetic envelope so the viseme cycle and the
  // measured-level path are both exercised without a real TTS stream.
  speechTimer = setInterval(() => {
    speakingLevel.value = Math.abs(Math.sin(Date.now() / 130)) * 0.9
  }, 33)
}

function cycleStatus() {
  const next = STATUSES[(STATUSES.indexOf(status.value) + 1) % STATUSES.length]
  status.value = next
}
</script>

<template>
  <main class="yxz-avatar-page">
    <section class="yxz-avatar-stage">
      <YXZPetScene
        v-model:state="mountState"
        :status="status"
        :speaking-level="speakingLevel"
        :paused="paused"
        @error="loadError = String($event)"
      />
    </section>
    <aside class="yxz-avatar-panel">
      <div class="row">
        <span class="key">状态</span>
        <span class="value">{{ STATUS_LABELS[status] }}</span>
        <button type="button" @click="cycleStatus">
          切换
        </button>
      </div>
      <div class="row">
        <button type="button" @click="toggleSpeech">
          {{ speechTimer ? '停止口型' : '模拟说话' }}
        </button>
        <button type="button" @click="paused = !paused">
          {{ paused ? '继续' : '暂停' }}
        </button>
      </div>
      <dl class="readout">
        <dt>挂载</dt>
        <dd>{{ mountState }}</dd>
        <dt>错误</dt>
        <dd>{{ loadError || '无' }}</dd>
      </dl>
    </aside>
  </main>
</template>

<style scoped>
.yxz-avatar-page {
  display: flex;
  min-height: 100dvh;
  background: #eef8fd;
  color: #15547c;
}

.yxz-avatar-stage {
  position: relative;
  flex: 1;
  min-width: 0;
}

.yxz-avatar-panel {
  display: flex;
  width: 15rem;
  flex-direction: column;
  gap: .9rem;
  padding: 1.1rem;
  border-left: 1px solid #b5dce9;
  background: #f7fcff;
  font-size: .85rem;
}

.row {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.key { color: #52758a; }
.value { font-weight: 600; }

.row button {
  padding: .35rem .7rem;
  border: 1px solid #8fcbe4;
  border-radius: .45rem;
  background: #fff;
  color: #087eae;
  cursor: pointer;
  font: inherit;
}

.row button:hover { background: #e6f6fd; }

.readout {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: .3rem .6rem;
  margin: 0;
}

.readout dt { color: #52758a; }
.readout dd { margin: 0; word-break: break-all; }
</style>

<route lang="yaml">
name: YXZAvatarQAPage
meta:
  layout: plain
</route>
