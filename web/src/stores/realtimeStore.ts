import { defineStore } from 'pinia'
import { getMe } from '../api/auth'
import { ApiError } from '../api/http'
import { useAuthStore } from './authStore'
import { useConversationStore } from './conversationStore'

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
const HEARTBEAT_INTERVAL_MS = 20_000
const HEARTBEAT_TIMEOUT_MS = 8_000
const MAX_RECONNECT_DELAY_MS = 15_000

interface RealtimeEvent {
  event: string
  data: Record<string, unknown>
}

export const useRealtimeStore = defineStore('realtime', {
  state: () => ({
    socket: null as WebSocket | null,
    connected: false,
    reconnectTimer: null as number | null,
    heartbeatTimer: null as number | null,
    heartbeatTimeoutTimer: null as number | null,
    refreshTimer: null as number | null,
    reconnectAttempt: 0,
    pendingMessageRefresh: false,
    manualDisconnect: false,
  }),
  actions: {
    connect() {
      if (
        this.socket?.readyState === WebSocket.OPEN ||
        this.socket?.readyState === WebSocket.CONNECTING
      ) {
        return
      }
      this.manualDisconnect = false
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }

      const socket = new WebSocket(`${WS_URL}/ws`)
      this.socket = socket
      socket.onopen = () => {
        if (this.socket !== socket) return
        this.connected = true
        this.reconnectAttempt = 0
        this.startHeartbeat(socket)
        void this.reconcileConversations(true)
      }
      socket.onclose = (event) => {
        if (this.socket !== socket) return
        this.connected = false
        this.socket = null
        this.clearHeartbeat()
        if (!this.manualDisconnect) void this.handleUnexpectedClose(event)
      }
      socket.onmessage = (messageEvent) => {
        if (messageEvent.data === 'pong') {
          if (this.heartbeatTimeoutTimer !== null) {
            window.clearTimeout(this.heartbeatTimeoutTimer)
            this.heartbeatTimeoutTimer = null
          }
          return
        }
        let realtimeEvent: RealtimeEvent
        try {
          realtimeEvent = JSON.parse(messageEvent.data) as RealtimeEvent
        } catch {
          return
        }
        const conversations = useConversationStore()
        const conversationId =
          typeof realtimeEvent.data?.conversation_id === 'string'
            ? realtimeEvent.data.conversation_id
            : null
        this.scheduleReconciliation(
          Boolean(
            realtimeEvent.event.startsWith('message.') &&
              conversationId &&
              conversations.selectedId === conversationId,
          ),
        )
      }
    },
    async handleUnexpectedClose(event: CloseEvent) {
      if (event.code !== 1008) {
        this.scheduleReconnect()
        return
      }
      try {
        useAuthStore().user = await getMe()
        this.scheduleReconnect()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          useAuthStore().clearSession()
          window.location.replace('/login?session=expired')
          return
        }
        this.scheduleReconnect()
      }
    },
    scheduleReconnect() {
      if (this.manualDisconnect || this.reconnectTimer !== null) return
      const delay = Math.min(
        1_000 * 2 ** this.reconnectAttempt,
        MAX_RECONNECT_DELAY_MS,
      )
      this.reconnectAttempt += 1
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null
        this.connect()
      }, delay)
    },
    startHeartbeat(socket: WebSocket) {
      this.clearHeartbeat()
      this.sendHeartbeat(socket)
      this.heartbeatTimer = window.setInterval(
        () => this.sendHeartbeat(socket),
        HEARTBEAT_INTERVAL_MS,
      )
    },
    sendHeartbeat(socket: WebSocket) {
      if (this.socket !== socket || socket.readyState !== WebSocket.OPEN) return
      if (this.heartbeatTimeoutTimer !== null) {
        window.clearTimeout(this.heartbeatTimeoutTimer)
      }
      try {
        socket.send('ping')
      } catch {
        socket.close()
        return
      }
      this.heartbeatTimeoutTimer = window.setTimeout(() => {
        if (this.socket === socket) socket.close()
      }, HEARTBEAT_TIMEOUT_MS)
    },
    clearHeartbeat() {
      if (this.heartbeatTimer !== null) {
        window.clearInterval(this.heartbeatTimer)
        this.heartbeatTimer = null
      }
      if (this.heartbeatTimeoutTimer !== null) {
        window.clearTimeout(this.heartbeatTimeoutTimer)
        this.heartbeatTimeoutTimer = null
      }
    },
    ensureConnected() {
      if (document.visibilityState !== 'visible') return
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.sendHeartbeat(this.socket)
        return
      }
      if (this.socket?.readyState === WebSocket.CONNECTING) return
      this.socket = null
      this.connect()
    },
    scheduleReconciliation(refreshMessages: boolean) {
      this.pendingMessageRefresh ||= refreshMessages
      if (this.refreshTimer !== null) return
      this.refreshTimer = window.setTimeout(() => {
        this.refreshTimer = null
        void this.reconcileConversations()
      }, 100)
    },
    async reconcileConversations(forceMessageRefresh = false) {
      const refreshMessages = this.pendingMessageRefresh || forceMessageRefresh
      this.pendingMessageRefresh = false
      const conversations = useConversationStore()
      try {
        await conversations.loadConversations()
        if (refreshMessages && conversations.selectedId) {
          await conversations.refreshMessages(conversations.selectedId)
        }
      } catch {
        // A reconexão ou o próximo evento tentará a conciliação novamente.
      }
    },
    disconnect() {
      this.manualDisconnect = true
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      if (this.refreshTimer !== null) {
        window.clearTimeout(this.refreshTimer)
        this.refreshTimer = null
      }
      this.pendingMessageRefresh = false
      this.clearHeartbeat()
      const socket = this.socket
      this.socket = null
      socket?.close()
      this.connected = false
      this.reconnectAttempt = 0
    },
  },
})
