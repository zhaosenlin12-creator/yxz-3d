<script setup lang="ts">
import { useChatMaintenanceStore } from '@proj-airi/stage-ui/stores/chat/maintenance'
import { useTheme } from '@proj-airi/ui'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { computed, defineAsyncComponent, ref } from 'vue'

import { BackgroundDialogPicker } from '../Backgrounds'

const { cleanupMessages } = useChatMaintenanceStore()
const { isDark, toggleDark } = useTheme()

const backgroundDialogOpen = ref(false)
const laserCardPanelOpen = ref(false)
const toolsOpen = ref(false)

// Dynamically import laser card panel to avoid circular dependencies
const YXZCreationWorkbench = computed(() => {
  return defineAsyncComponent(async () => {
    // 走包入口而不是直接引 .vue：stage-ui 的 exports 只把 .ts 暴露成子路径，
    // 直接引 .vue 路径 vue-tsc 解析不到（运行时 vite 能兜住，类型检查不行）。
    const scenes = await import('@proj-airi/stage-ui/components/scenes')
    return scenes.YXZCreationWorkbench
  })
})

function handleLaserCardStatus(status: string) {
  if (status === 'sent') {
    laserCardPanelOpen.value = false
  }
}

function openLaserCard() {
  toolsOpen.value = false
  laserCardPanelOpen.value = true
}

function openBackground() {
  toolsOpen.value = false
  backgroundDialogOpen.value = true
}

function clearConversation() {
  toolsOpen.value = false
  cleanupMessages()
}
</script>

<template>
  <BackgroundDialogPicker v-model="backgroundDialogOpen" />

  <!-- Laser card panel -->
  <component
    :is="YXZCreationWorkbench"
    v-if="laserCardPanelOpen"
    v-model:open="laserCardPanelOpen"
    mode="laser"
    @status="handleLaserCardStatus"
  />

  <!--
    One entry point, not four.

    These used to sit side by side in the corner, which read as four
    equally important actions and gave the exhibition screen a busy strip of
    chrome. They are all secondary utilities, so they now live behind a
    single "工具" button, grouped by what they actually affect.
  -->
  <PopoverRoot v-model:open="toolsOpen">
    <PopoverTrigger as-child>
      <button
        class="absolute bottom--8 right-0 max-h-[10lh] min-h-[1lh]"
        bg="neutral-100 dark:neutral-800"
        text="lg neutral-500 dark:neutral-400"
        hover:text="orange-500 dark:orange-400"
        flex items-center justify-center rounded-md p-2 outline-none
        transition-colors transition-transform active:scale-95
        title="工具"
        aria-label="工具"
      >
        <div i-solar:widget-4-bold-duotone />
      </button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        side="top"
        align="end"
        :side-offset="8"
        class="z-50 w-60 rounded-xl border border-neutral-200/60 bg-neutral-50/95 p-1.5 shadow-lg backdrop-blur-md dark:border-neutral-800/30 dark:bg-neutral-900/90"
      >
        <span class="block px-2.5 pt-1.5 pb-1 text-[11px] tracking-wide text-neutral-400">创作</span>
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs text-neutral-700 outline-none transition-colors hover:bg-primary-100/60 dark:text-neutral-200 dark:hover:bg-primary-900/40"
          @click="openLaserCard"
        >
          <div i-solar:card-bold-duotone class="h-4 w-4 shrink-0 text-orange-500 dark:text-orange-400" />
          <span class="flex-1">制作激光切割名片</span>
        </button>

        <span class="block px-2.5 pt-2 pb-1 text-[11px] tracking-wide text-neutral-400">会话</span>
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs text-neutral-700 outline-none transition-colors hover:bg-primary-100/60 dark:text-neutral-200 dark:hover:bg-primary-900/40"
          @click="clearConversation"
        >
          <div i-solar:trash-bin-2-bold-duotone class="h-4 w-4 shrink-0 text-red-500 dark:text-red-400" />
          <span class="flex-1">清空当前对话</span>
        </button>

        <span class="block px-2.5 pt-2 pb-1 text-[11px] tracking-wide text-neutral-400">外观</span>
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs text-neutral-700 outline-none transition-colors hover:bg-primary-100/60 dark:text-neutral-200 dark:hover:bg-primary-900/40"
          @click="toggleDark()"
        >
          <span class="h-4 w-4 shrink-0">
            <Transition name="fade" mode="out-in">
              <div v-if="isDark" i-solar:moon-bold />
              <div v-else i-solar:sun-2-bold />
            </Transition>
          </span>
          <span class="flex-1">{{ isDark ? '切回浅色模式' : '切换深色模式' }}</span>
        </button>
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs text-neutral-700 outline-none transition-colors hover:bg-primary-100/60 dark:text-neutral-200 dark:hover:bg-primary-900/40"
          @click="openBackground"
        >
          <div i-solar:gallery-wide-bold-duotone class="h-4 w-4 shrink-0 text-orange-500 dark:text-orange-400" />
          <span class="flex-1">更换背景</span>
        </button>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
