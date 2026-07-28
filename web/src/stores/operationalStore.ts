import { defineStore } from 'pinia'
import { getOperationalHealth } from '../api/operations'
import type { OperationalHealth } from '../api/types'

const POLL_INTERVAL = 30_000

export const useOperationalStore = defineStore('operational', {
  state: () => ({
    health: null as OperationalHealth | null,
    loading: false,
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
