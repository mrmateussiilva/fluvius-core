import { http } from './http'
import type {
  ContactDetail,
  ContactListItem,
  ContactListResponse,
  ContactSearchResult,
  Conversation,
} from './types'

export const listContacts = (params: {
  q?: string
  limit?: number
  offset?: number
} = {}) => {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  const suffix = query.toString()
  return http<ContactListResponse>(`/api/v1/contacts${suffix ? `?${suffix}` : ''}`)
}

export const createContact = (payload: { name: string; phone_number: string }) =>
  http<ContactListItem>('/api/v1/contacts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const getContact = (id: string) => http<ContactDetail>(`/api/v1/contacts/${id}`)

export const updateContact = (id: string, payload: { name: string | null }) =>
  http<ContactDetail>(`/api/v1/contacts/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const searchContacts = (query: string) =>
  http<ContactSearchResult[]>(
    `/api/v1/contacts/search?q=${encodeURIComponent(query)}`,
  )

export const startContactConversation = (id: string, channelId: string) =>
  http<Conversation>(`/api/v1/contacts/${id}/conversations`, {
    method: 'POST',
    body: JSON.stringify({ channel_id: channelId }),
  })

export const refreshContact = (id: string, channelId: string) =>
  http<ContactDetail>(`/api/v1/contacts/${id}/refresh`, {
    method: 'POST',
    body: JSON.stringify({ channel_id: channelId }),
  })
