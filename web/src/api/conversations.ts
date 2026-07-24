import { http } from './http'
import type { Conversation } from './types'

export const listConversations = () => http<Conversation[]>('/api/v1/conversations')
export const getConversation = (id: string) => http<Conversation>(`/api/v1/conversations/${id}`)
export const assignConversation = (id: string) =>
  http<Conversation>(`/api/v1/conversations/${id}/assign`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
export const closeConversation = (id: string) =>
  http<Conversation>(`/api/v1/conversations/${id}/close`, { method: 'POST' })
export const markConversationRead = (id: string, throughMessageId: string) =>
  http<void>(`/api/v1/conversations/${id}/read`, {
    method: 'POST',
    body: JSON.stringify({ through_message_id: throughMessageId }),
  })
