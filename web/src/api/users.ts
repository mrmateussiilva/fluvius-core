import { http } from './http'
import type { ActiveTenantUser, TenantUser, UserRole } from './types'

export interface CreateUserPayload {
  name: string
  email: string
  password: string
  role: UserRole
  channel_ids?: string[]
}

export interface UpdateUserPayload {
  name?: string
  password?: string
  role?: UserRole
  is_active?: boolean
  channel_ids?: string[]
}

export const listUsers = () => http<TenantUser[]>('/api/v1/users')

export const listActiveUsers = () =>
  http<ActiveTenantUser[]>('/api/v1/users/active')

export const createUser = (payload: CreateUserPayload) =>
  http<TenantUser>('/api/v1/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateUser = (id: string, payload: UpdateUserPayload) =>
  http<TenantUser>(`/api/v1/users/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
