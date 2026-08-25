import { http } from './http'
import type { Message } from './types'

export const listMessages = (
  conversationId: string,
  limit = 100,
  before: string | null = null,
) => {
  const params = new URLSearchParams()
  if (limit) params.set('limit', String(limit))
  if (before) params.set('before', before)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return http<Message[]>(`/api/v1/conversations/${conversationId}/messages${qs}`)
}
export const sendMessage = (
  conversationId: string,
  text: string,
  clientMessageId: string,
  replyToMessageId: string | null = null,
  mentionedPhones: string[] = [],
  mentionedJids: string[] = [],
  referencedContactIds: string[] = [],
  isInternal: boolean = false,
) =>
  http<Message>(`/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      text,
      reply_to_message_id: replyToMessageId,
      mentioned_phones: mentionedPhones,
      mentioned_jids: mentionedJids,
      referenced_contact_ids: referencedContactIds,
      client_message_id: clientMessageId,
      is_internal: isInternal,
    }),
  })

export const sendAttachment = (
  conversationId: string,
  file: File,
  clientMessageId: string,
  caption: string | null = null,
  replyToMessageId: string | null = null,
  mentionedPhones: string[] = [],
  mentionedJids: string[] = [],
  referencedContactIds: string[] = [],
) => {
  const body = new FormData()
  body.append('file', file)
  body.append('client_message_id', clientMessageId)
  if (caption) body.append('caption', caption)
  if (replyToMessageId) body.append('reply_to_message_id', replyToMessageId)
  for (const phone of mentionedPhones) body.append('mentioned_phones', phone)
  for (const jid of mentionedJids) body.append('mentioned_jids', jid)
  for (const contactId of referencedContactIds) {
    body.append('referenced_contact_ids', contactId)
  }
  return http<Message>(`/api/v1/conversations/${conversationId}/attachments`, {
    method: 'POST',
    body,
  })
}

export const sendContact = (
  conversationId: string,
  contactId: string,
  clientMessageId: string,
  replyToMessageId: string | null = null,
) =>
  http<Message>(`/api/v1/conversations/${conversationId}/contacts`, {
    method: 'POST',
    body: JSON.stringify({
      contact_id: contactId,
      client_message_id: clientMessageId,
      reply_to_message_id: replyToMessageId,
    }),
  })

export const retryMessage = (conversationId: string, messageId: string) =>
  http<Message>(`/api/v1/conversations/${conversationId}/messages/${messageId}/retry`, {
    method: 'POST',
  })
