import { computed, type Ref } from 'vue'
import type { ChannelStatus } from '../api/types'

export function useChannelStatus(status: Ref<ChannelStatus>) {
  const isConnected = computed(() => status.value === 'connected')
  const label = computed(() =>
    isConnected.value ? 'WhatsApp conectado' : 'WhatsApp desconectado',
  )
  return { isConnected, label }
}
