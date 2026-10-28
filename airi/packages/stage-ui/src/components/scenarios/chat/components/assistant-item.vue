<script setup lang="ts">
import type { ChatAssistantMessage, ChatHistoryItem, ChatSlices, ChatSlicesText } from '../../../../types/chat'

import { isStageCapacitor, isStageWeb } from '@proj-airi/stage-shared'
import { computed } from 'vue'

import YXZCreationMessageCard from '../../../scenes/YXZCreationMessageCard.vue'
import YXZLaserCardMessageCard from '../../../scenes/YXZLaserCardMessageCard.vue'
import ChatResponsePart from './response-part.vue'
import ChatToolCallBlock from './tool-call-block.vue'

import { MarkdownRenderer } from '../../../markdown'
import { getChatHistoryItemCopyText } from '../utils'
import { ChatActionMenu } from './action-menu'

const props = withDefaults(defineProps<{
  message: ChatAssistantMessage
  label: string
  showPlaceholder?: boolean
  variant?: 'desktop' | 'mobile'
}>(), {
  showPlaceholder: false,
  variant: 'desktop',
})

const emit = defineEmits<{
  (e: 'copy'): void
  (e: 'delete'): void
  (e: 'adoptCreation'): void
  (e: 'redescribeCreation'): void
}>()

const resolvedSlices = computed<ChatSlices[]>(() => {
  if (props.message.slices?.length) {
    return props.message.slices
  }

  if (typeof props.message.content === 'string' && props.message.content.trim()) {
    return [{ type: 'text', text: props.message.content } satisfies ChatSlicesText]
  }

  if (Array.isArray(props.message.content)) {
    const textPart = props.message.content.find(part => 'type' in part && part.type === 'text') as { text?: string } | undefined
    if (textPart?.text)
      return [{ type: 'text', text: textPart.text } satisfies ChatSlicesText]
  }

  return []
})

const showLoader = computed(() => props.showPlaceholder && resolvedSlices.value.length === 0)
// A tool call is in flight (preview / 3D generation / laser svg...) — show an explicit
// "making" hint so the user never thinks the chat froze.
const toolPending = computed(() => {
  if (props.showPlaceholder)
    return false
  const slices = props.message.slices ?? []
  const last = slices.at(-1)
  return !!last && last.type === 'tool-call'
})
const containerClass = computed(() => props.variant === 'mobile' ? 'mr-0' : 'mr-12')
const boxClasses = computed(() => [
  props.variant === 'mobile' ? 'px-2 py-2 text-sm bg-primary-50/90 dark:bg-primary-950/90' : 'px-3 py-3 bg-primary-50/80 dark:bg-primary-950/80',
])
const copyText = computed(() => getChatHistoryItemCopyText(props.message as ChatHistoryItem))
const creation = computed(() => props.message.yxzCreation)
const laserCard = computed(() => props.message.yxzLaserCard)
const isInternalTool = (toolName: string) => toolName.startsWith('builtIn_')
const hideInternalFailure = computed(() => !creation.value && !laserCard.value
  && props.message.slices?.some(slice => slice.type === 'tool-call' && isInternalTool(slice.toolCall.toolName)))
</script>

<template>
  <div v-if="!hideInternalFailure" flex :class="containerClass" class="ph-no-capture">
    <ChatActionMenu
      :copy-text="copyText"
      :can-delete="!showPlaceholder"
      @copy="emit('copy')"
      @delete="emit('delete')"
    >
      <template #default="{ setMeasuredElement }">
        <div
          :ref="setMeasuredElement"
          flex="~ col" shadow="sm primary-200/50 dark:none"
          min-w-20 rounded-xl h="unset <sm:fit"
          :class="[
            boxClasses,
            (isStageWeb() || isStageCapacitor()) && props.variant === 'mobile' ? 'select-none sm:select-auto' : '',
          ]"
        >
          <div>
            <span text-sm text="black/60 dark:white/65" font-normal class="inline <sm:hidden">{{ label }}</span>
          </div>
          <div v-if="resolvedSlices.length > 0" class="break-words" text="primary-700 dark:primary-100">
            <template v-for="(slice, sliceIndex) in resolvedSlices" :key="sliceIndex">
              <ChatToolCallBlock
                v-if="slice.type === 'tool-call' && !isInternalTool(slice.toolCall.toolName)"
                :tool-name="slice.toolCall.toolName"
                :args="slice.toolCall.args"
                class="mb-2"
              />
              <template v-else-if="slice.type === 'tool-call-result'" />
              <template v-else-if="slice.type === 'text'">
                <MarkdownRenderer :content="slice.text" />
              </template>
            </template>
          </div>
          <div v-else-if="showLoader" class="flex items-center gap-2 py-0.5">
            <div i-eos-icons:three-dots-loading />
            <span class="text-xs text-primary-600/70 dark:text-primary-200/70">宜小智 正在思考，请稍候…</span>
          </div>
          <div v-else-if="toolPending" class="flex items-center gap-2 py-0.5 text-xs text-primary-600/70 dark:text-primary-200/70">
            <div i-eos-icons:three-dots-loading />
            <span>宜小智 正在制作，请耐心等待…</span>
          </div>

          <ChatResponsePart
            v-if="message.categorization"
            :message="message"
            :variant="variant"
          />

          <YXZCreationMessageCard
            v-if="creation"
            :preview-src="creation.preview.src"
            :caption="creation.preview.caption"
            :description="creation.description"
            :previews="creation.previews"
            :model-url="creation.model?.glbUrl"
            :stl-url="creation.model?.stlUrl"
            :session-id="creation.sessionId"
            :status="creation.status"
            :progress-msg="creation.progressMsg"
            :error-msg="creation.errorMsg"
            :interactive="false"
            class="mt-3"
          />
          <YXZLaserCardMessageCard
            v-if="laserCard"
            :session-id="laserCard.sessionId"
            :svg-url="laserCard.svgUrl"
            :png-url="laserCard.pngUrl"
            :front-url="laserCard.frontUrl"
            :back-url="laserCard.backUrl"
            :size-mm="laserCard.sizeMm"
            :back-template="laserCard.backTemplate"
            :artwork-session-id="laserCard.artworkSessionId"
            :artwork-image-index="laserCard.artworkImageIndex"
            :name="laserCard.name"
            :description="laserCard.description"
            :has-artwork="laserCard.hasArtwork"
            class="mt-3"
          />
        </div>
      </template>
    </ChatActionMenu>
  </div>
</template>
