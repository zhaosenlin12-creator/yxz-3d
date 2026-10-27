<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'

const emit = defineEmits<{
  (e: 'confirm', imageDataUrl: string, blob: Blob): void
  (e: 'cancel'): void
}>()

const videoRef = ref<HTMLVideoElement>()
const canvasRef = ref<HTMLCanvasElement>()
const capturedImage = ref<string>()
const isCameraActive = ref(false)
const isLoading = ref(false)
let stream: MediaStream | null = null

async function startCamera() {
  if (isLoading.value)
    return

  isLoading.value = true

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280, max: 1920 },
        height: { ideal: 720, max: 1080 },
        facingMode: 'user', // 前置摄像头
      },
      audio: false,
    })

    if (videoRef.value) {
      videoRef.value.srcObject = stream
      isCameraActive.value = true
      toast.success('摄像头已打开')
    }
  }
  catch (error: any) {
    console.error('无法访问摄像头:', error)
    const errorMessage = error.name === 'NotAllowedError'
      ? '摄像头权限被拒绝，请在浏览器设置中允许访问摄像头'
      : '无法访问摄像头，请检查设备连接'
    toast.error(errorMessage)
  }
  finally {
    isLoading.value = false
  }
}

function capture() {
  if (!videoRef.value || !canvasRef.value)
    return

  const video = videoRef.value
  const canvas = canvasRef.value

  // 设置画布尺寸与视频一致
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight

  const ctx = canvas.getContext('2d')
  if (!ctx)
    return

  // 绘制当前帧到画布
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

  // 转换为 data URL
  capturedImage.value = canvas.toDataURL('image/jpeg', 0.9)

  // 停止摄像头
  stopCamera()

  toast.success('照片已拍摄')
}

function retake() {
  capturedImage.value = undefined
  startCamera()
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach(track => track.stop())
    stream = null
    isCameraActive.value = false
  }
}

async function confirm() {
  if (!capturedImage.value)
    return

  try {
    // 将 data URL 转换为 Blob
    const response = await fetch(capturedImage.value)
    const blob = await response.blob()

    emit('confirm', capturedImage.value, blob)
  }
  catch (error) {
    console.error('图片处理失败:', error)
    toast.error('图片处理失败，请重试')
  }
}

function cancel() {
  stopCamera()
  emit('cancel')
}

// 组件卸载时清理资源
onUnmounted(() => {
  stopCamera()
})

// 自动启动摄像头
startCamera()
</script>

<template>
  <div class="camera-capture">
    <!-- 摄像头预览区域 -->
    <div class="preview-area">
      <!-- 视频流 -->
      <video
        v-show="isCameraActive && !capturedImage"
        ref="videoRef"
        autoplay
        playsinline
        class="video-preview"
      />

      <!-- 隐藏的画布用于捕获帧 -->
      <canvas ref="canvasRef" style="display: none" />

      <!-- 拍摄的照片预览 -->
      <img
        v-if="capturedImage"
        :src="capturedImage"
        alt="Captured"
        class="image-preview"
      >

      <!-- 加载状态 -->
      <div v-if="isLoading" class="loading-overlay">
        <div class="spinner" />
        <p>正在打开摄像头...</p>
      </div>

      <!-- 提示信息 -->
      <div v-if="!isCameraActive && !capturedImage && !isLoading" class="hint">
        <p>📷 准备拍照</p>
        <p class="hint-text">
          点击下方按钮开始
        </p>
      </div>
    </div>

    <!-- 控制按钮 -->
    <div class="controls">
      <!-- 开始拍照 -->
      <button
        v-if="!isCameraActive && !capturedImage"
        class="btn btn-primary"
        :disabled="isLoading"
        @click="startCamera"
      >
        <span class="icon">📷</span>
        <span>打开摄像头</span>
      </button>

      <!-- 拍照 -->
      <button
        v-if="isCameraActive && !capturedImage"
        class="btn btn-capture"
        @click="capture"
      >
        <span class="icon">📸</span>
        <span>拍照</span>
      </button>

      <!-- 重拍 -->
      <button
        v-if="capturedImage"
        class="btn btn-secondary"
        @click="retake"
      >
        <span class="icon">🔄</span>
        <span>重拍</span>
      </button>

      <!-- 确认使用 -->
      <button
        v-if="capturedImage"
        class="btn btn-primary"
        @click="confirm"
      >
        <span class="icon">✅</span>
        <span>确认使用</span>
      </button>

      <!-- 取消 -->
      <button
        class="btn btn-text"
        @click="cancel"
      >
        取消
      </button>
    </div>
  </div>
</template>

<style scoped>
.camera-capture {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
}

.preview-area {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-preview,
.image-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  color: white;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.hint {
  text-align: center;
  color: rgba(255, 255, 255, 0.9);
}

.hint p:first-child {
  font-size: 3rem;
  margin: 0 0 0.5rem 0;
}

.hint-text {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0;
}

.controls {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  justify-content: center;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-capture {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: white;
  padding: 1rem 2rem;
  font-size: 1.125rem;
}

.btn-capture:hover {
  transform: scale(1.05);
  box-shadow: 0 6px 20px rgba(245, 87, 108, 0.4);
}

.btn-secondary {
  background: #f3f4f6;
  color: #374151;
}

.btn-secondary:hover {
  background: #e5e7eb;
}

.btn-text {
  background: transparent;
  color: #6b7280;
}

.btn-text:hover {
  color: #374151;
}

.icon {
  font-size: 1.25em;
}

@media (max-width: 640px) {
  .camera-capture {
    max-width: 100%;
  }

  .preview-area {
    border-radius: 8px;
  }

  .btn {
    font-size: 0.875rem;
    padding: 0.625rem 1.25rem;
  }

  .btn-capture {
    font-size: 1rem;
    padding: 0.875rem 1.75rem;
  }
}
</style>
