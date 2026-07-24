import { defineStore } from 'pinia'
import * as contactApi from '../api/contacts'
import * as conversationApi from '../api/conversations'
import * as messageApi from '../api/messages'
import type { ContactDetail, Conversation, Message } from '../api/types'

export const useConversationStore = defineStore('conversations', {
  state: () => ({
    conversations: [] as Conversation[],
    selectedId: null as string | null,
    messagesByConversation: {} as Record<string, Message[]>,
    contactsById: {} as Record<string, ContactDetail>,
    contactLoading: false,
    contactError: null as string | null,
    retryingMessageIds: [] as string[],
    sending: false,
    sendError: null as string | null,
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
    async send(text: string, replyToMessageId: string | null = null) {
      if (!this.selectedId || this.sending) return
      const conversationId = this.selectedId
      this.sending = true
      this.sendError = null
      try {
        const message = await messageApi.sendMessage(conversationId, text, replyToMessageId)
        this.upsertMessage(conversationId, message)
        this.updateConversationPreview(conversationId, message)
      } catch (error) {
        this.sendError =
          error instanceof Error ? error.message : 'Não foi possível enviar a mensagem'
      } finally {
        this.sending = false
      }
    },
    async sendAttachment(
      file: File,
      caption: string | null = null,
      replyToMessageId: string | null = null,
    ) {
      if (!this.selectedId || this.sending) return
      const conversationId = this.selectedId
      this.sending = true
      this.sendError = null
      try {
        const message = await messageApi.sendAttachment(
          conversationId,
          file,
          caption,
          replyToMessageId,
        )
        this.upsertMessage(conversationId, message)
        this.updateConversationPreview(conversationId, message)
      } catch (error) {
        this.sendError = error instanceof Error ? error.message : 'Não foi possível enviar o anexo'
      } finally {
        this.sending = false
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
      if (!this.selectedId) return
      const updated = await conversationApi.assignConversation(this.selectedId)
      this.replace(updated)
    },
    async closeSelected() {
      if (!this.selectedId) return
      const updated = await conversationApi.closeConversation(this.selectedId)
      this.replace(updated)
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
          : messages.map((message) => (message.id === updated.id ? updated : message))
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
