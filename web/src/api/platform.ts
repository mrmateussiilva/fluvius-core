import { http } from './http'
import type { PlatformTenant, PlatformTenantDetail } from './types'

export interface CreatePlatformTenantPayload {
  name: string
  slug: string
  admin_name: string
  admin_email: string
  admin_password: string
}

export const listPlatformTenants = () =>
  http<PlatformTenant[]>('/api/v1/platform/tenants')

export const getPlatformTenant = (tenantId: string) =>
  http<PlatformTenantDetail>(`/api/v1/platform/tenants/${tenantId}`)

export const createPlatformTenant = (payload: CreatePlatformTenantPayload) =>
  http<PlatformTenant>('/api/v1/platform/tenants', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updatePlatformTenant = (
  tenantId: string,
  isActive: boolean,
) =>
  http<PlatformTenant>(`/api/v1/platform/tenants/${tenantId}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  })

export async function accessPlatformTenant(tenantId: string): Promise<void> {
  await http<{ access_token: string }>(
    `/api/v1/platform/tenants/${tenantId}/access`,
    { method: 'POST' },
  )
}
