import { defineStore } from 'pinia'
import * as contactApi from '../api/contacts'
import * as conversationApi from '../api/conversations'
import * as messageApi from '../api/messages'
import type { ContactDetail, ContactSearchResult, Conversation, Message } from '../api/types'
import { useAuthStore } from './authStore'

const messageStatusRank: Record<Message['status'], number> = {
  pending: 0,
  sent: 1,
  delivered: 2,
  read: 3,
  failed: 4,
}

function messageTypeForFile(file: File): Message['message_type'] {
  const normalizedType = file.type.toLowerCase()
  const extension = `.${file.name.toLowerCase().split('.').pop() || ''}`
  if (normalizedType === 'image/webp' || extension === '.webp') return 'sticker'
  if (
    normalizedType.startsWith('image/') ||
    ['.gif', '.jpeg', '.jpg', '.png'].includes(extension)
  ) {
    return 'image'
  }
  if (
    normalizedType.startsWith('audio/') ||
    ['.aac', '.flac', '.m4a', '.mp3', '.oga', '.ogg', '.wav', '.weba'].includes(
      extension,
    )
  ) {
    return 'audio'
  }
  if (
    normalizedType.startsWith('video/') ||
    ['.m4v', '.mov', '.mp4', '.webm'].includes(extension)
  ) {
    return 'video'
  }
  return 'document'
}

export const useConversationStore = defineStore('conversations', {
  state: () => ({
    conversations: [] as Conversation[],
    selectedId: null as string | null,
    messagesByConversation: {} as Record<string, Message[]>,
    contactsById: {} as Record<string, ContactDetail>,
    contactLoading: false,
    contactError: null as string | null,
    retryingMessageIds: [] as string[],
    sendingConversationIds: [] as string[],
    markingReadConversationIds: [] as string[],
    activeReadMessageIds: {} as Record<string, string | null>,
    pendingReadMessageIds: {} as Record<string, string | null>,
    sendErrorsByConversation: {} as Record<string, string | null>,
    operationLoading: false,
    operationError: null as string | null,
    loading: false,
    activeChannelId: null as string | null,
    hasMoreMessagesByConversation: {} as Record<string, boolean>,
    loadingOlderMessages: false,
  }),
  getters: {
    selected(state): Conversation | null {
      return state.conversations.find((item) => item.id === state.selectedId) || null
    },
    selectedMessages(state): Message[] {
      return state.selectedId ? state.messagesByConversation[state.selectedId] || [] : []
    },
    selectedContact(state): ContactDetail | null {
      const conversation = state.conversations.find((item) => item.id === state.selectedId)
      return conversation ? state.contactsById[conversation.contact_id] || null : null
    },
    selectedSending(state): boolean {
      return Boolean(
        state.selectedId && state.sendingConversationIds.includes(state.selectedId),
      )
    },
    selectedSendError(state): string | null {
      return state.selectedId
        ? state.sendErrorsByConversation[state.selectedId] || null
        : null
    },
  },
  actions: {
    async loadConversations(channelId?: string | null) {
      const requestedChannelId =
        channelId === undefined ? this.activeChannelId : channelId
      this.loading = true
      this.activeChannelId = requestedChannelId
      try {
        this.conversations =
          await conversationApi.listConversations(requestedChannelId)
        if (
          this.selectedId &&
          !this.conversations.some((conversation) => conversation.id === this.selectedId)
        ) {
          this.selectedId = null
        }
        if (!this.selectedId && this.conversations.length) {
          this.selectedId = this.conversations[0].id
        }
      } finally {
        this.loading = false
      }
    },
    async selectConversation(id: string) {
      this.selectedId = id
      this.operationError = null
      const conversation = this.selected
      await Promise.all([
        this.refreshMessages(id),
        conversation?.contact_kind === 'group'
          ? this.loadSelectedContact()
          : Promise.resolve(),
      ])
    },
    async refreshMessages(id: string) {
      const existing = this.messagesByConversation[id] || []
      const limit = Math.max(existing.length, 100)
      const fetched = await messageApi.listMessages(id, limit)
      this.messagesByConversation[id] = fetched
      this.hasMoreMessagesByConversation[id] = fetched.length >= limit
    },
    async loadOlderMessages(id: string): Promise<boolean> {
      if (this.loadingOlderMessages) return false
      if (this.hasMoreMessagesByConversation[id] === false) return false
      const current = this.messagesByConversation[id] || []
      if (!current.length) return false
      const oldest = current[0]
      this.loadingOlderMessages = true
      try {
        const older = await messageApi.listMessages(id, 50, oldest.created_at)
        if (!older.length) {
          this.hasMoreMessagesByConversation[id] = false
          return false
        }
        const existingIds = new Set(current.map((m) => m.id))
        const filteredOlder = older.filter((m) => !existingIds.has(m.id))
        this.messagesByConversation[id] = [...filteredOlder, ...current]
        this.hasMoreMessagesByConversation[id] = older.length >= 50
        return filteredOlder.length > 0
      } catch {
        return false
      } finally {
        this.loadingOlderMessages = false
      }
    },
    async markConversationRead(id: string, throughMessageId: string) {
      const conversation = this.conversations.find((item) => item.id === id)
      if (!conversation?.unread_count) {
        return
      }
      if (this.markingReadConversationIds.includes(id)) {
        if (this.activeReadMessageIds[id] !== throughMessageId) {
          this.pendingReadMessageIds[id] = throughMessageId
        }
        return
      }
      this.markingReadConversationIds.push(id)
      this.activeReadMessageIds[id] = throughMessageId
      try {
        let nextMessageId: string | null = throughMessageId
        while (nextMessageId) {
          this.activeReadMessageIds[id] = nextMessageId
          try {
            await conversationApi.markConversationRead(id, nextMessageId)
          } catch {
            // Keep the unread count so a later visible-bottom event can retry.
          }
          nextMessageId = this.pendingReadMessageIds[id] || null
          delete this.pendingReadMessageIds[id]
        }
      } finally {
        delete this.activeReadMessageIds[id]
        delete this.pendingReadMessageIds[id]
        this.markingReadConversationIds =
          this.markingReadConversationIds.filter(
            (conversationId) => conversationId !== id,
          )
        try {
          this.replace(await conversationApi.getConversation(id))
        } catch {
          // Realtime or a later refresh will reconcile the unread count.
        }
      }
    },
    async send(
      text: string,
      replyToMessageId: string | null = null,
      mentionedPhones: string[] = [],
      mentionedJids: string[] = [],
      referencedContactIds: string[] = [],
    ): Promise<boolean> {
      if (
        !this.selectedId ||
        this.sendingConversationIds.includes(this.selectedId)
      ) {
        return false
      }
      const conversationId = this.selectedId
      const clientMessageId = crypto.randomUUID()
      const createdAt = new Date().toISOString()
      const senderName =
        useAuthStore().user?.name?.trim().replace(/\s+/g, ' ') || null
      const reply = (this.messagesByConversation[conversationId] || []).find(
        (message) => message.id === replyToMessageId,
      )
      const optimisticMessage: Message = {
        id: clientMessageId,
        conversation_id: conversationId,
        direction: 'outgoing',
        message_type: 'text',
        status: 'pending',
        body: text,
        mentioned_phones: mentionedPhones,
        mentioned_jids: mentionedJids,
        referenced_contacts: [],
        shared_contacts: [],
        reply_to_message_id: replyToMessageId,
        reply_to_provider_message_id: reply?.provider_message_id || null,
        reply_to: reply
          ? {
              id: reply.id,
              direction: reply.direction,
              message_type: reply.message_type,
              body: reply.body,
              sender_name: reply.sender_name,
              participant_name: reply.participant_name,
            }
          : null,
        attachments: [],
        sender_name: senderName,
        participant_phone: null,
        participant_name: null,
        provider_message_id: null,
        error: null,
        attempt_count: 1,
        last_attempt_at: createdAt,
        sent_at: null,
        delivered_at: null,
        read_at: null,
        edited_at: null,
        edit_content_unavailable: false,
        is_bot: false,
        created_at: createdAt,
      }
      this.sendingConversationIds.push(conversationId)
      this.sendErrorsByConversation[conversationId] = null
      this.upsertMessage(conversationId, optimisticMessage)
      try {
        const message = await messageApi.sendMessage(
          conversationId,
          text,
          clientMessageId,
          replyToMessageId,
          mentionedPhones,
          mentionedJids,
          referencedContactIds,
        )
        this.upsertMessage(conversationId, message)
        this.updateConversationPreview(conversationId, message)
        return true
      } catch (error) {
        try {
          await this.refreshMessages(conversationId)
        } catch {
          // Preserve the original request error below.
        }
        const persisted = (
          this.messagesByConversation[conversationId] || []
        ).some(
          (message) =>
            message.id === clientMessageId && message !== optimisticMessage,
        )
        if (persisted) return true
        this.removeMessage(conversationId, clientMessageId)
        this.sendErrorsByConversation[conversationId] =
          error instanceof Error
            ? error.message
            : 'Não foi possível enviar a mensagem'
        return false
      } finally {
        this.sendingConversationIds = this.sendingConversationIds.filter(
          (id) => id !== conversationId,
        )
      }
    },
    async sendAttachments(
      files: File[],
      caption: string | null = null,
      replyToMessageId: string | null = null,
      mentionedPhones: string[] = [],
      mentionedJids: string[] = [],
      referencedContactIds: string[] = [],
    ): Promise<number[]> {
      if (
        !this.selectedId ||
        this.sendingConversationIds.includes(this.selectedId) ||
        !files.length
      ) {
        return []
      }
      const conversationId = this.selectedId
      const senderName =
        useAuthStore().user?.name?.trim().replace(/\s+/g, ' ') || null
      const reply = (this.messagesByConversation[conversationId] || []).find(
        (message) => message.id === replyToMessageId,
      )
      const captionIndex = files.findIndex(
        (file) => messageTypeForFile(file) !== 'sticker',
      )
      const acceptedIndexes: number[] = []
      this.sendingConversationIds.push(conversationId)
      this.sendErrorsByConversation[conversationId] = null
      try {
        for (const [index, file] of files.entries()) {
          const clientMessageId = crypto.randomUUID()
          const createdAt = new Date().toISOString()
          const previewUrl = URL.createObjectURL(file)
          const messageType = messageTypeForFile(file)
          const isCaptionTarget = index === captionIndex
          const isReplyTarget = index === 0
          const optimisticMessage: Message = {
            id: clientMessageId,
            conversation_id: conversationId,
            direction: 'outgoing',
            message_type: messageType,
            status: 'pending',
            body: isCaptionTarget ? caption : null,
            mentioned_phones: isCaptionTarget ? mentionedPhones : [],
            mentioned_jids: isCaptionTarget ? mentionedJids : [],
            referenced_contacts: [],
            shared_contacts: [],
            reply_to_message_id: isReplyTarget ? replyToMessageId : null,
            reply_to_provider_message_id:
              isReplyTarget ? reply?.provider_message_id || null : null,
            reply_to:
              isReplyTarget && reply
                ? {
                    id: reply.id,
                    direction: reply.direction,
                    message_type: reply.message_type,
                    body: reply.body,
                    sender_name: reply.sender_name,
                    participant_name: reply.participant_name,
                  }
                : null,
            attachments: [
              {
                id: crypto.randomUUID(),
                file_name: file.name || 'anexo',
                content_type: file.type || 'application/octet-stream',
                size_bytes: file.size,
                public_url: previewUrl,
              },
            ],
            sender_name: senderName,
            participant_phone: null,
            participant_name: null,
            provider_message_id: null,
            error: null,
            attempt_count: 1,
            last_attempt_at: createdAt,
            sent_at: null,
            delivered_at: null,
            read_at: null,
            edited_at: null,
            edit_content_unavailable: false,
            is_bot: false,
            created_at: createdAt,
          }
          this.upsertMessage(conversationId, optimisticMessage)
          try {
            const message = await messageApi.sendAttachment(
              conversationId,
              file,
              clientMessageId,
              isCaptionTarget ? caption : null,
              isReplyTarget ? replyToMessageId : null,
              isCaptionTarget ? mentionedPhones : [],
              isCaptionTarget ? mentionedJids : [],
              isCaptionTarget ? referencedContactIds : [],
            )
            this.upsertMessage(conversationId, message)
            this.updateConversationPreview(conversationId, message)
            acceptedIndexes.push(index)
          } catch (error) {
            try {
              await this.refreshMessages(conversationId)
            } catch {
              // Preserve the original request error below.
            }
            const persisted = (
              this.messagesByConversation[conversationId] || []
            ).some(
              (message) =>
                message.id === clientMessageId &&
                message.attachments.every(
                  (attachment) => attachment.public_url !== previewUrl,
                ),
            )
            if (persisted) {
              acceptedIndexes.push(index)
            } else {
              this.removeMessage(conversationId, clientMessageId)
              this.sendErrorsByConversation[conversationId] =
                error instanceof Error
                  ? error.message
                  : `Não foi possível enviar ${file.name || 'o anexo'}`
            }
          } finally {
            URL.revokeObjectURL(previewUrl)
          }
        }
        return acceptedIndexes
      } finally {
        this.sendingConversationIds = this.sendingConversationIds.filter(
          (id) => id !== conversationId,
        )
      }
    },
    async sendContact(
      contact: ContactSearchResult,
      replyToMessageId: string | null = null,
    ): Promise<boolean> {
      if (
        !this.selectedId ||
        this.sendingConversationIds.includes(this.selectedId)
      ) {
        return false
      }
      const conversationId = this.selectedId
      const clientMessageId = crypto.randomUUID()
      const createdAt = new Date().toISOString()
      const senderName =
        useAuthStore().user?.name?.trim().replace(/\s+/g, ' ') || null
      const reply = (this.messagesByConversation[conversationId] || []).find(
        (message) => message.id === replyToMessageId,
      )
      const optimisticMessage: Message = {
        id: clientMessageId,
        conversation_id: conversationId,
        direction: 'outgoing',
        message_type: 'contact',
        status: 'pending',
        body: null,
        mentioned_phones: [],
        mentioned_jids: [],
        referenced_contacts: [],
        shared_contacts: [
          {
            id: crypto.randomUUID(),
            source_contact_id: contact.id,
            display_name: contact.display_name,
            phone_number: contact.phone_number,
            organization: null,
          },
        ],
        reply_to_message_id: replyToMessageId,
        reply_to_provider_message_id: reply?.provider_message_id || null,
        reply_to: reply
          ? {
              id: reply.id,
              direction: reply.direction,
              message_type: reply.message_type,
              body: reply.body,
              sender_name: reply.sender_name,
              participant_name: reply.participant_name,
            }
          : null,
        attachments: [],
        sender_name: senderName,
        participant_phone: null,
        participant_name: null,
        provider_message_id: null,
        error: null,
        attempt_count: 1,
        last_attempt_at: createdAt,
        sent_at: null,
        delivered_at: null,
        read_at: null,
        edited_at: null,
        edit_content_unavailable: false,
        is_bot: false,
        created_at: createdAt,
      }
      this.sendingConversationIds.push(conversationId)
      this.sendErrorsByConversation[conversationId] = null
      this.upsertMessage(conversationId, optimisticMessage)
      try {
        const message = await messageApi.sendContact(
          conversationId,
          contact.id,
          clientMessageId,
          replyToMessageId,
        )
        this.upsertMessage(conversationId, message)
        this.updateConversationPreview(conversationId, message)
        return true
      } catch (error) {
        try {
          await this.refreshMessages(conversationId)
        } catch {
          // Preserve the original request error below.
        }
        const persisted = (
          this.messagesByConversation[conversationId] || []
        ).some((message) => message.id === clientMessageId)
        if (persisted) return true
        this.removeMessage(conversationId, clientMessageId)
        this.sendErrorsByConversation[conversationId] =
          error instanceof Error
            ? error.message
            : 'Não foi possível compartilhar o contato'
        return false
      } finally {
        this.sendingConversationIds = this.sendingConversationIds.filter(
          (id) => id !== conversationId,
        )
      }
    },
    async retryMessage(messageId: string) {
      if (!this.selectedId || this.retryingMessageIds.includes(messageId)) return
      const conversationId = this.selectedId
      this.retryingMessageIds.push(messageId)
      try {
        const updated = await messageApi.retryMessage(conversationId, messageId)
        this.messagesByConversation[conversationId] = (
          this.messagesByConversation[conversationId] || []
        ).map((message) => (message.id === updated.id ? updated : message))
      } catch (error) {
        const detail = error instanceof Error ? error.message : 'Não foi possível reenviar'
        this.messagesByConversation[conversationId] = (
          this.messagesByConversation[conversationId] || []
        ).map((message) => (message.id === messageId ? { ...message, error: detail } : message))
      } finally {
        this.retryingMessageIds = this.retryingMessageIds.filter((id) => id !== messageId)
      }
    },
    async loadSelectedContact(forceRefresh = false) {
      const conversation = this.selected
      if (!conversation || this.contactLoading) return
      this.contactLoading = true
      this.contactError = null
      try {
        let contact = this.contactsById[conversation.contact_id]
        if (!contact || forceRefresh) {
          contact = forceRefresh
            ? await contactApi.refreshContact(conversation.contact_id, conversation.channel_id)
            : await contactApi.getContact(conversation.contact_id)
          this.contactsById[contact.id] = contact
        }
        const groupNeedsMembers =
          conversation.contact_kind === 'group' &&
          (!contact.group_members || contact.group_members.length === 0)
        if (!forceRefresh && (!contact.profile_synced_at || groupNeedsMembers)) {
          const refreshed = await contactApi.refreshContact(
            conversation.contact_id,
            conversation.channel_id,
          )
          this.contactsById[refreshed.id] = refreshed
        }
      } catch (error) {
        this.contactError = error instanceof Error ? error.message : 'Não foi possível carregar o contato'
      } finally {
        this.contactLoading = false
      }
    },
    async assignSelected(userId?: string) {
      if (!this.selectedId || this.operationLoading) return
      this.operationLoading = true
      this.operationError = null
      try {
        const updated = await conversationApi.assignConversation(this.selectedId, userId)
        this.replace(updated)
      } catch (error) {
        this.operationError =
          error instanceof Error ? error.message : 'Não foi possível atribuir o atendimento'
        await this.loadConversations()
      } finally {
        this.operationLoading = false
      }
    },
    async closeSelected() {
      if (!this.selectedId || this.operationLoading) return
      this.operationLoading = true
      this.operationError = null
      try {
        const updated = await conversationApi.closeConversation(this.selectedId)
        this.replace(updated)
      } catch (error) {
        this.operationError =
          error instanceof Error ? error.message : 'Não foi possível finalizar o atendimento'
        await this.loadConversations()
      } finally {
        this.operationLoading = false
      }
    },
    replace(updated: Conversation) {
      this.conversations = this.conversations.map((item) => (item.id === updated.id ? updated : item))
    },
    upsertMessage(conversationId: string, updated: Message) {
      const messages = this.messagesByConversation[conversationId] || []
      const existing = messages.findIndex((message) => message.id === updated.id)
      this.messagesByConversation[conversationId] =
        existing === -1
          ? [...messages, updated]
          : messages.map((message) => {
              if (message.id !== updated.id) return message
              if (
                message.status === 'failed' ||
                updated.status === 'failed' ||
                messageStatusRank[message.status] <= messageStatusRank[updated.status]
              ) {
                return updated
              }
              return {
                ...updated,
                status: message.status,
                sent_at: message.sent_at || updated.sent_at,
                delivered_at: message.delivered_at || updated.delivered_at,
                read_at: message.read_at || updated.read_at,
              }
            })
    },
    removeMessage(conversationId: string, messageId: string) {
      this.messagesByConversation[conversationId] = (
        this.messagesByConversation[conversationId] || []
      ).filter((message) => message.id !== messageId)
    },
    updateConversationPreview(conversationId: string, message: Message) {
      this.conversations = this.conversations.map((item) =>
        item.id === conversationId
          ? {
              ...item,
              last_message_at: message.created_at,
              last_message_body: message.body,
              last_message_type: message.message_type,
              last_message_direction: message.direction,
            }
          : item,
      )
    },
  },
})
