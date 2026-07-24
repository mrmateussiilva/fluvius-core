import { http } from './http'
import type { CurrentUser } from './types'

export async function login(email: string, password: string): Promise<string> {
  const response = await http<{ access_token: string }>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return response.access_token
}

export const getMe = () => http<CurrentUser>('/api/v1/auth/me')
