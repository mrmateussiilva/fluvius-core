<script setup lang="ts">
import { computed } from 'vue'
import { Circle } from 'lucide-vue-next'
import type { ChannelStatus } from '../api/types'

const props = defineProps<{ status: ChannelStatus }>()
const appearance = computed(() => {
  const appearances: Record<
    ChannelStatus,
    { label: string; className: string; dotClass: string }
  > = {
    disconnected: {
      label: 'Desconectado',
      className: 'border-slate-200 bg-slate-50 text-slate-600',
      dotClass: 'text-slate-400',
    },
    connecting: {
      label: 'Conectando',
      className: 'border-amber-200 bg-amber-50 text-amber-700',
      dotClass: 'animate-pulse text-amber-500',
    },
    connected: {
      label: 'WhatsApp conectado',
      className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      dotClass: 'text-emerald-500',
    },
    requires_qr: {
      label: 'Aguardando QR',
      className: 'border-sky-200 bg-sky-50 text-sky-700',
      dotClass: 'animate-pulse text-sky-500',
    },
    failed: {
      label: 'Falha na conexão',
      className: 'border-rose-200 bg-rose-50 text-rose-700',
      dotClass: 'text-rose-500',
    },
  }
  return appearances[props.status]
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold"
    :class="appearance.className"
  >
    <span class="relative flex h-2 w-2">
      <span
        v-if="status === 'connected'"
        class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-30"
      />
      <Circle class="relative h-2 w-2" :class="appearance.dotClass" fill="currentColor" />
    </span>
    {{ appearance.label }}
  </span>
</template>
