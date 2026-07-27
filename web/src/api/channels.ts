import { http } from './http'
import type { Channel, ChannelStatus } from './types'

export interface ChannelConnectionResult {
  qr_code: string | null
  pairing_code: string | null
  status: ChannelStatus
  error: string | null
}

export const listChannels = () => http<Channel[]>('/api/v1/channels')
export const createChannel = (payload: {
  name: string
  phone_number?: string
  provider: Channel['provider']
  provider_config?: Record<string, unknown>
  provisioning_key?: string
}) => http<Channel>('/api/v1/channels', { method: 'POST', body: JSON.stringify(payload) })
export const getChannelStatus = (id: string) =>
  http<{ status: ChannelStatus; raw_status: string | null; error: string | null }>(
    `/api/v1/channels/${id}/status`,
  )
export const connectChannel = (id: string) =>
  http<ChannelConnectionResult>(
    `/api/v1/channels/${id}/connect`,
    { method: 'POST' },
  )
export const getChannelQr = (id: string) =>
  http<ChannelConnectionResult>(
    `/api/v1/channels/${id}/qr`,
  )
