<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listQuickReplies } from '../api/quickReplies'
import type { QuickReply } from '../api/types'

const emit = defineEmits<{ select: [content: string] }>()
const replies = ref<QuickReply[]>([])

onMounted(async () => {
  try {
    replies.value = await listQuickReplies()
  } catch {
    replies.value = []
  }
})
</script>

<template>
  <div class="absolute bottom-full left-0 z-30 mb-2 w-80 overflow-hidden rounded-xl border border-black/5 bg-white p-2 shadow-2xl">
    <p class="border-b border-[#e9edef] px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#667781]">Respostas rápidas</p>
    <button
      v-for="reply in replies"
      :key="reply.id"
      class="mt-1 block w-full rounded-lg px-2.5 py-2 text-left transition hover:bg-[#f0f2f5]"
      @click="emit('select', reply.content)"
    >
      <span class="block text-sm font-medium text-[#111b21]">{{ reply.title }}</span>
      <span class="mt-0.5 block truncate text-xs text-[#667781]">/{{ reply.shortcut }} · {{ reply.content }}</span>
    </button>
    <p v-if="!replies.length" class="px-2 py-4 text-center text-xs text-[#667781]">Nenhuma resposta cadastrada.</p>
  </div>
</template>
