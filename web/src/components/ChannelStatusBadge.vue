<script setup lang="ts">
import { computed } from 'vue'
import { Circle } from 'lucide-vue-next'
import type { ChannelStatus } from '../api/types'

const props = defineProps<{ status: ChannelStatus }>()
const connected = computed(() => props.status === 'connected')
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold"
    :class="connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'"
  >
    <span class="relative flex h-2 w-2">
      <span v-if="connected" class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-30" />
      <Circle class="relative h-2 w-2" fill="currentColor" />
    </span>
    {{ connected ? 'WhatsApp conectado' : 'WhatsApp desconectado' }}
  </span>
</template>
