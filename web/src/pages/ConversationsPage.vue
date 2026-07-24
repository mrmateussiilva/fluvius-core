<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import ConversationChat from '../components/ConversationChat.vue'
import ConversationList from '../components/ConversationList.vue'
import { useConversationStore } from '../stores/conversationStore'
import { useAuthStore } from '../stores/authStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const store = useConversationStore()
const auth = useAuthStore()
const realtime = useRealtimeStore()

async function refreshVisibleConversation() {
  if (document.visibilityState !== 'visible' || !store.selectedId) return
  await store.loadConversations()
  await store.refreshMessages(store.selectedId, true)
}

onMounted(async () => {
  await auth.restore()
  await store.loadConversations()
  if (store.selectedId) await store.selectConversation(store.selectedId)
  realtime.connect()
  document.addEventListener('visibilitychange', refreshVisibleConversation)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', refreshVisibleConversation)
})
</script>

<template>
  <div class="flex h-full min-h-0">
    <ConversationList
      :conversations="store.conversations"
      :selected-id="store.selectedId"
      :current-user-id="auth.user?.id || null"
      @select="store.selectConversation"
    />
    <ConversationChat
      :conversation="store.selected"
      :messages="store.selectedMessages"
      :contact="store.selectedContact"
      :contact-loading="store.contactLoading"
      :contact-error="store.contactError"
      :retrying-message-ids="store.retryingMessageIds"
      :sending="store.sending"
      :send-error="store.sendError"
      @assign="store.assignSelected"
      @close="store.closeSelected"
      @send="store.send"
      @send-attachment="store.sendAttachment"
      @retry="store.retryMessage"
      @show-contact="store.loadSelectedContact()"
      @refresh-contact="store.loadSelectedContact(true)"
    />
  </div>
</template>
