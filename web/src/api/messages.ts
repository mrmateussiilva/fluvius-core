import { http } from './http'
import type { Message } from './types'

export const listMessages = (conversationId: string) =>
  http<Message[]>(`/api/v1/conversations/${conversationId}/messages`)
export const sendMessage = (
  conversationId: string,
  text: string,
  clientMessageId: string,
  replyToMessageId: string | null = null,
  mentionedPhones: string[] = [],
  referencedContactIds: string[] = [],
) =>
  http<Message>(`/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      text,
      reply_to_message_id: replyToMessageId,
      mentioned_phones: mentionedPhones,
      referenced_contact_ids: referencedContactIds,
      client_message_id: clientMessageId,
    }),
  })

export const sendAttachment = (
  conversationId: string,
  file: File,
  clientMessageId: string,
  caption: string | null = null,
  replyToMessageId: string | null = null,
  mentionedPhones: string[] = [],
  referencedContactIds: string[] = [],
) => {
  const body = new FormData()
  body.append('file', file)
  body.append('client_message_id', clientMessageId)
  if (caption) body.append('caption', caption)
  if (replyToMessageId) body.append('reply_to_message_id', replyToMessageId)
  for (const phone of mentionedPhones) body.append('mentioned_phones', phone)
  for (const contactId of referencedContactIds) {
    body.append('referenced_contact_ids', contactId)
  }
  return http<Message>(`/api/v1/conversations/${conversationId}/attachments`, {
    method: 'POST',
    body,
  })
}

export const retryMessage = (conversationId: string, messageId: string) =>
  http<Message>(`/api/v1/conversations/${conversationId}/messages/${messageId}/retry`, {
    method: 'POST',
  })
