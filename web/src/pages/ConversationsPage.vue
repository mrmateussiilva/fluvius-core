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

async function sendMessage(
  text: string,
  replyToMessageId: string | null,
  done: (accepted: boolean) => void,
) {
  done(await store.send(text, replyToMessageId))
}

async function sendAttachment(
  file: File,
  caption: string | null,
  replyToMessageId: string | null,
  done: (accepted: boolean) => void,
) {
  done(await store.sendAttachment(file, caption, replyToMessageId))
}

async function refreshVisibleConversation() {
  if (document.visibilityState !== 'visible' || !store.selectedId) return
  await store.loadConversations()
  await store.refreshMessages(store.selectedId)
}

function backToConversationList() {
  store.selectedId = null
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
      :class="store.selectedId ? 'hidden md:flex' : 'flex'"
      :conversations="store.conversations"
      :selected-id="store.selectedId"
      :current-user-id="auth.user?.id || null"
      @select="store.selectConversation"
    />
    <ConversationChat
      :class="store.selectedId ? 'flex' : 'hidden md:flex'"
      :conversation="store.selected"
      :messages="store.selectedMessages"
      :contact="store.selectedContact"
      :contact-loading="store.contactLoading"
      :contact-error="store.contactError"
      :retrying-message-ids="store.retryingMessageIds"
      :current-user-id="auth.user?.id || null"
      :sending="store.selectedSending"
      :send-error="store.selectedSendError"
      :operation-loading="store.operationLoading"
      :operation-error="store.operationError"
      @assign="store.assignSelected"
      @close="store.closeSelected"
      @send="sendMessage"
      @send-attachment="sendAttachment"
      @retry="store.retryMessage"
      @read="store.markConversationRead"
      @back="backToConversationList"
      @show-contact="store.loadSelectedContact()"
      @refresh-contact="store.loadSelectedContact(true)"
    />
  </div>
</template>
