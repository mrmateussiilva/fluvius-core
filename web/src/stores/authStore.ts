import { defineStore } from 'pinia'
import {
  getMe,
  login,
  logout,
  switchTenant as switchTenantRequest,
  updateMe,
} from '../api/auth'
import type { UpdateCurrentUserPayload } from '../api/auth'
import type { CurrentUser } from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as CurrentUser | null,
    loading: false,
  }),
  actions: {
    async signIn(email: string, password: string, tenantSlug?: string) {
      this.loading = true
      try {
        await login(email, password, tenantSlug)
        this.user = await getMe()
      } finally {
        this.loading = false
      }
    },
    async restore() {
      if (!this.user) this.user = await getMe()
    },
    async refresh() {
      this.user = await getMe()
    },
    async updateProfile(payload: UpdateCurrentUserPayload) {
      this.user = await updateMe(payload)
      return this.user
    },
    async switchTenant(tenantId: string) {
      await switchTenantRequest(tenantId)
      await this.refresh()
    },
    async signOut() {
      try {
        await logout()
      } finally {
        this.user = null
      }
    },
    clearSession() {
      this.user = null
    },
  },
})
