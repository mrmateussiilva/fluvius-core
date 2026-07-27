import { defineStore } from 'pinia'
import { getMe, login, logout } from '../api/auth'
import type { CurrentUser } from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as CurrentUser | null,
    loading: false,
  }),
  actions: {
    async signIn(email: string, password: string) {
      this.loading = true
      try {
        await login(email, password)
        this.user = await getMe()
      } finally {
        this.loading = false
      }
    },
    async restore() {
      if (!this.user) this.user = await getMe()
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
