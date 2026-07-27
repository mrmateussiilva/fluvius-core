import { http } from './http'
import type { SyncRun, SyncType } from './types'

export const listSyncRuns = (channelId?: string) => {
  const query = channelId
    ? `?channel_id=${encodeURIComponent(channelId)}`
    : ''
  return http<SyncRun[]>(`/api/v1/admin/sync-runs${query}`)
}

export const getSyncRun = (id: string) =>
  http<SyncRun>(`/api/v1/admin/sync-runs/${id}`)

export const createSyncRun = (payload: {
  channel_id: string
  sync_type: SyncType
  recent_days: number
}) =>
  http<SyncRun>('/api/v1/admin/sync-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
