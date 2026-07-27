import { http } from './http'
import type { CurrentUser } from './types'

export async function login(email: string, password: string): Promise<void> {
  await http<{ access_token: string }>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export const getMe = () => http<CurrentUser>('/api/v1/auth/me')

export const logout = () =>
  http<void>('/api/v1/auth/logout', {
    method: 'POST',
  })
