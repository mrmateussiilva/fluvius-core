import { defineStore } from 'pinia'
import * as contactApi from '../api/contacts'
import * as conversationApi from '../api/conversations'
import * as messageApi from '../api/messages'
import type { ContactDetail, Conversation, Message } from '../api/types'

const messageStatusRank: Record<Message['status'], number> = {
  pending: 0,
  sent: 1,
  delivered: 2,
  read: 3,
  failed: 4,
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
    sendErrorsByConversation: {} as Record<string, string | null>,
    operationLoading: false,
    operationError: null as string | null,
    loading: false,
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
    async loadConversations() {
      this.loading = true
      try {
        this.conversations = await conversationApi.listConversations()
        if (!this.selectedId && this.conversations.length) this.selectedId = this.conversations[0].id
      } finally {
        this.loading = false
      }
    },
    async selectConversation(id: string) {
      this.selectedId = id
      this.operationError = null
      await this.refreshMessages(id, true)
    },
    async refreshMessages(id: string, markAsRead = false) {
      this.messagesByConversation[id] = await messageApi.listMessages(id)
      if (markAsRead && this.selectedId === id && document.visibilityState === 'visible') {
        await conversationApi.markConversationRead(id)
        this.conversations = this.conversations.map((item) =>
          item.id === id ? { ...item, unread_count: 0 } : item,
        )
      }
    },
    async send(
      text: string,
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
        reply_to_message_id: replyToMessageId,
        reply_to_provider_message_id: reply?.provider_message_id || null,
        reply_to: reply
          ? {
              id: reply.id,
              direction: reply.direction,
              message_type: reply.message_type,
              body: reply.body,
            }
          : null,
        attachments: [],
        provider_message_id: null,
        error: null,
        attempt_count: 1,
        last_attempt_at: createdAt,
        sent_at: null,
        delivered_at: null,
        read_at: null,
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
            : 'Não foi possível enviar a mensagem'
        return false
      } finally {
        this.sendingConversationIds = this.sendingConversationIds.filter(
          (id) => id !== conversationId,
        )
      }
    },
    async sendAttachment(
      file: File,
      caption: string | null = null,
      replyToMessageId: string | null = null,
    ): Promise<boolean> {
      if (
        !this.selectedId ||
        this.sendingConversationIds.includes(this.selectedId)
      ) {
        return false
      }
      const conversationId = this.selectedId
      this.sendingConversationIds.push(conversationId)
      this.sendErrorsByConversation[conversationId] = null
      try {
        const message = await messageApi.sendAttachment(
          conversationId,
          file,
          caption,
          replyToMessageId,
        )
        this.upsertMessage(conversationId, message)
        this.updateConversationPreview(conversationId, message)
        return true
      } catch (error) {
        this.sendErrorsByConversation[conversationId] =
          error instanceof Error ? error.message : 'Não foi possível enviar o anexo'
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
        if (!forceRefresh && !contact.profile_synced_at) {
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
    async assignSelected() {
      if (!this.selectedId || this.operationLoading) return
      this.operationLoading = true
      this.operationError = null
      try {
        const updated = await conversationApi.assignConversation(this.selectedId)
        this.replace(updated)
      } catch (error) {
        this.operationError =
          error instanceof Error ? error.message : 'Não foi possível assumir o atendimento'
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
