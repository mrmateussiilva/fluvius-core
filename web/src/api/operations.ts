import { http } from './http'
import type {
  OperationalHealth,
  WebhookReconcileResult,
} from './types'

export const getOperationalHealth = () =>
  http<OperationalHealth>('/api/v1/operations/health')

export const reconcileWebhooks = (payload: {
  channel_id?: string | null
  limit_per_channel?: number
} = {}) =>
  http<WebhookReconcileResult>('/api/v1/operations/webhooks/reconcile', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
