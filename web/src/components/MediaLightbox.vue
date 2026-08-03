<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { Download, X } from 'lucide-vue-next'
import type { MessageAttachment, MessageType } from '../api/types'

const props = defineProps<{
  attachment: MessageAttachment
  messageType: MessageType
}>()
const emit = defineEmits<{ close: [] }>()
let previousBodyOverflow = ''

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-[80] flex flex-col bg-black/95 text-white backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Visualização de mídia"
      @click.self="emit('close')"
    >
      <header class="flex h-16 shrink-0 items-center justify-between gap-4 bg-black/20 px-4 sm:px-6">
        <div class="min-w-0">
          <p class="truncate text-sm font-medium">{{ attachment.file_name }}</p>
          <p class="mt-0.5 text-[11px] text-white/55">{{ attachment.content_type }}</p>
        </div>
        <div class="flex items-center gap-1">
          <a
            :href="attachment.public_url"
            :download="attachment.file_name"
            target="_blank"
            rel="noopener noreferrer"
            class="grid h-10 w-10 place-items-center rounded-full text-white/80 transition hover:bg-white/10 hover:text-white"
            title="Baixar arquivo"
          >
            <Download class="h-5 w-5" />
          </a>
          <button
            class="grid h-10 w-10 place-items-center rounded-full text-white/80 transition hover:bg-white/10 hover:text-white"
            title="Fechar"
            @click="emit('close')"
          >
            <X class="h-5 w-5" />
          </button>
        </div>
      </header>

      <div class="grid min-h-0 flex-1 place-items-center p-4 sm:p-8" @click.self="emit('close')">
        <img
          v-if="messageType === 'image' || messageType === 'sticker'"
          :src="attachment.public_url"
          :alt="attachment.file_name"
          class="max-h-full max-w-full select-none object-contain drop-shadow-2xl"
        />
        <video
          v-else-if="messageType === 'video'"
          class="max-h-full max-w-full rounded-lg bg-black shadow-2xl"
          controls
          autoplay
          :src="attachment.public_url"
        >
          Seu navegador não suporta vídeo.
        </video>
      </div>
    </div>
  </Teleport>
</template>
