import { defineStore } from 'pinia'
import { useConversationStore } from './conversationStore'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

interface RealtimeEvent {
  event: string
  data: Record<string, unknown>
}

export const useRealtimeStore = defineStore('realtime', {
  state: () => ({ socket: null as WebSocket | null, connected: false }),
  actions: {
    connect() {
      const token = localStorage.getItem('fluvius_token')
      if (!token || this.socket) return
      this.socket = new WebSocket(`${WS_URL}/ws?token=${encodeURIComponent(token)}`)
      this.socket.onopen = () => (this.connected = true)
      this.socket.onclose = () => {
        this.connected = false
        this.socket = null
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
          await conversations.refreshMessages(
            conversationId,
            document.visibilityState === 'visible',
          )
        }
      }
    },
    disconnect() {
      this.socket?.close()
      this.socket = null
      this.connected = false
    },
  },
})
