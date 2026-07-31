import { defineStore } from 'pinia'
import {
  getOperationalHealth,
  reconcileWebhooks,
} from '../api/operations'
import type {
  OperationalHealth,
  WebhookReconcileResult,
} from '../api/types'

const POLL_INTERVAL = 30_000

export const useOperationalStore = defineStore('operational', {
  state: () => ({
    health: null as OperationalHealth | null,
    lastReconcile: null as WebhookReconcileResult | null,
    loading: false,
    reconciling: false,
    error: '',
    pollTimer: null as number | null,
  }),
  actions: {
    async refresh() {
      if (this.loading) return
      this.loading = true
      try {
        this.health = await getOperationalHealth()
        this.error = ''
      } catch (exception) {
        this.error =
          exception instanceof Error
            ? exception.message
            : 'Não foi possível consultar a saúde operacional'
      } finally {
        this.loading = false
      }
    },
    async reconcile(channelId?: string) {
      if (this.reconciling) return
      this.reconciling = true
      try {
        this.lastReconcile = await reconcileWebhooks({
          channel_id: channelId || null,
          limit_per_channel: 1000,
        })
        this.error = ''
        await this.refresh()
      } catch (exception) {
        this.error =
          exception instanceof Error
            ? exception.message
            : 'Não foi possível reconciliar os webhooks'
      } finally {
        this.reconciling = false
      }
    },
    startPolling() {
      this.stopPolling()
      void this.refresh()
      this.pollTimer = window.setInterval(() => {
        if (document.visibilityState === 'visible') void this.refresh()
      }, POLL_INTERVAL)
    },
    stopPolling() {
      if (this.pollTimer !== null) {
        window.clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
  },
})
