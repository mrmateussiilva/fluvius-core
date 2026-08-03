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
      className: 'border-line bg-canvas text-ink-secondary',
      dotClass: 'text-ink-faint',
    },
    connecting: {
      label: 'Conectando',
      className: 'border-warning/30 bg-warning-soft text-warning-strong',
      dotClass: 'animate-pulse text-warning',
    },
    connected: {
      label: 'WhatsApp conectado',
      className: 'border-success/30 bg-success-soft text-success-strong',
      dotClass: 'text-success',
    },
    requires_qr: {
      label: 'Aguardando QR',
      className: 'border-info/30 bg-info-soft text-info-strong',
      dotClass: 'animate-pulse text-info',
    },
    failed: {
      label: 'Falha na conexão',
      className: 'border-danger/30 bg-danger-soft text-danger-strong',
      dotClass: 'text-danger',
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
        class="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-30"
      />
      <Circle class="relative h-2 w-2" :class="appearance.dotClass" fill="currentColor" />
    </span>
    {{ appearance.label }}
  </span>
</template>
