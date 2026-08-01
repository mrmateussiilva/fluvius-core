import { http } from './http'
import type { ContactDetail, ContactSearchResult } from './types'

export const getContact = (id: string) => http<ContactDetail>(`/api/v1/contacts/${id}`)

export const searchContacts = (query: string) =>
  http<ContactSearchResult[]>(
    `/api/v1/contacts/search?q=${encodeURIComponent(query)}`,
  )

export const refreshContact = (id: string, channelId: string) =>
  http<ContactDetail>(`/api/v1/contacts/${id}/refresh`, {
    method: 'POST',
    body: JSON.stringify({ channel_id: channelId }),
  })
