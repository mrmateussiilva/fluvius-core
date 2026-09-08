import { http } from './http'
import type { TypebotConfigRead, TypebotConfigWrite } from './types'

export async function fetchTypebotConfig(
  channelId: string,
): Promise<TypebotConfigRead> {
  return http<TypebotConfigRead>(`/api/v1/channels/${channelId}/typebot-config`)
}

export async function saveTypebotConfig(
  channelId: string,
  payload: TypebotConfigWrite,
): Promise<TypebotConfigRead> {
  return http<TypebotConfigRead>(`/api/v1/channels/${channelId}/typebot-config`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}
