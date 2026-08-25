import { http } from './http'
import type {
  AiConfigRead,
  AiConfigUpdate,
  AiSimulateRequest,
  AiSimulateResponse,
} from './types'

export async function fetchAiConfig(channelId: string): Promise<AiConfigRead> {
  return http<AiConfigRead>(`/api/v1/channels/${channelId}/ai-config`)
}

export async function saveAiConfig(
  channelId: string,
  payload: AiConfigUpdate,
): Promise<AiConfigRead> {
  return http<AiConfigRead>(`/api/v1/channels/${channelId}/ai-config`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function simulateAi(
  channelId: string,
  payload: AiSimulateRequest,
): Promise<AiSimulateResponse> {
  return http<AiSimulateResponse>(
    `/api/v1/channels/${channelId}/ai-simulator`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export async function toggleConversationBot(
  conversationId: string,
  isBotActive: boolean,
  reason?: string,
): Promise<{ success: boolean; is_bot_active: boolean }> {
  return http<{ success: boolean; is_bot_active: boolean }>(
    `/api/v1/conversations/${conversationId}/toggle-bot`,
    {
      method: 'POST',
      body: JSON.stringify({ is_bot_active: isBotActive, reason }),
    },
  )
}

export async function summarizeConversation(
  conversationId: string,
): Promise<{ summary: string; generated_at: string }> {
  return http<{ summary: string; generated_at: string }>(
    `/api/v1/conversations/${conversationId}/summarize`,
    {
      method: 'POST',
    },
  )
}
