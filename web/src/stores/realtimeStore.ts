import { defineStore } from 'pinia'
import { getMe } from '../api/auth'
import { useAuthStore } from './authStore'
import { useConversationStore } from './conversationStore'

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

interface RealtimeEvent {
  event: string
  data: Record<string, unknown>
}

export const useRealtimeStore = defineStore('realtime', {
  state: () => ({
    socket: null as WebSocket | null,
    connected: false,
    reconnectTimer: null as number | null,
    manualDisconnect: false,
  }),
  actions: {
    connect() {
      if (this.socket) return
      this.manualDisconnect = false
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      this.socket = new WebSocket(`${WS_URL}/ws`)
      this.socket.onopen = () => (this.connected = true)
      this.socket.onclose = () => {
        this.connected = false
        this.socket = null
        if (!this.manualDisconnect) {
          this.reconnectTimer = window.setTimeout(async () => {
            try {
              useAuthStore().user = await getMe()
              this.connect()
            } catch {
              useAuthStore().clearSession()
              window.location.replace('/login?session=expired')
            }
          }, 1_000)
        }
      }
      this.socket.onmessage = async (messageEvent) => {
        let realtimeEvent: RealtimeEvent
        try {
          realtimeEvent = JSON.parse(messageEvent.data) as RealtimeEvent
        } catch {
          return
        }
        const conversations = useConversationStore()
        await conversations.loadConversations()
        const conversationId =
          typeof realtimeEvent.data?.conversation_id === 'string'
            ? realtimeEvent.data.conversation_id
            : null
        if (
          realtimeEvent.event.startsWith('message.') &&
          conversationId &&
          conversations.selectedId === conversationId
        ) {
          await conversations.refreshMessages(conversationId)
        }
      }
    },
    disconnect() {
      this.manualDisconnect = true
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      this.socket?.close()
      this.socket = null
      this.connected = false
    },
  },
})
