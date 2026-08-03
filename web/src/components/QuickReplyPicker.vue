<script setup lang="ts">
import type { QuickReply } from '../api/types'

defineProps<{
  activeIndex: number
  error: string | null
  loading: boolean
  query: string
  replies: QuickReply[]
}>()
const emit = defineEmits<{
  select: [reply: QuickReply]
  hover: [index: number]
}>()
</script>

<template>
  <div class="absolute bottom-full left-0 z-30 mb-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-black/5 bg-panel p-2 shadow-2xl">
    <div class="border-b border-line px-2 pb-2 pt-1">
      <p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        Respostas rápidas
      </p>
      <p v-if="query" class="mt-0.5 truncate text-xs text-ink-faint">
        /{{ query }}
      </p>
    </div>
    <p
      v-if="loading"
      class="px-2 py-4 text-center text-xs text-ink-muted"
    >
      Carregando respostas...
    </p>
    <p
      v-else-if="error"
      class="px-2 py-4 text-center text-xs text-danger"
    >
      {{ error }}
    </p>
    <button
      v-for="(reply, index) in replies"
      :key="reply.id"
      class="mt-1 block w-full rounded-lg px-2.5 py-2 text-left transition"
      :class="
        index === activeIndex
          ? 'bg-fluvius-50 text-fluvius-900 dark:text-emerald-100'
          : 'hover:bg-panel-muted'
      "
      @mouseenter="emit('hover', index)"
      @mousedown.prevent="emit('select', reply)"
    >
      <span class="block text-sm font-medium text-ink">{{ reply.title }}</span>
      <span class="mt-0.5 block truncate text-xs text-ink-muted">/{{ reply.shortcut }} · {{ reply.content }}</span>
    </button>
    <p
      v-if="!loading && !error && !replies.length"
      class="px-2 py-4 text-center text-xs text-ink-muted"
    >
      {{
        query
          ? 'Nenhuma resposta encontrada.'
          : 'Nenhuma resposta cadastrada.'
      }}
    </p>
  </div>
</template>
