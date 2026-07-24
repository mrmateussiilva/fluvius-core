import { defineStore } from 'pinia'
import { getMe, login } from '../api/auth'
import type { CurrentUser } from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('fluvius_token') as string | null,
    user: null as CurrentUser | null,
    loading: false,
  }),
  actions: {
    async signIn(email: string, password: string) {
      this.loading = true
      try {
        this.token = await login(email, password)
        localStorage.setItem('fluvius_token', this.token)
        this.user = await getMe()
      } finally {
        this.loading = false
      }
    },
    async restore() {
      if (this.token && !this.user) this.user = await getMe()
    },
    signOut() {
      this.token = null
      this.user = null
      localStorage.removeItem('fluvius_token')
    },
  },
})
