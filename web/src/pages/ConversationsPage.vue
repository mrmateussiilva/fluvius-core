<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { listChannels } from '../api/channels'
import type { Channel, ContactSearchResult, TenantUser } from '../api/types'
import { listUsers } from '../api/users'
import ConversationChat from '../components/ConversationChat.vue'
import ConversationList from '../components/ConversationList.vue'
import { useConversationStore } from '../stores/conversationStore'
import { useAuthStore } from '../stores/authStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const store = useConversationStore()
const auth = useAuthStore()
const realtime = useRealtimeStore()
const route = useRoute()
const assignableUsers = ref<TenantUser[]>([])
const channels = ref<Channel[]>([])

function channelStorageKey() {
  return auth.user
    ? `fluvius_active_channel:${auth.user.tenant_id}:${auth.user.id}`
    : null
}

async function selectChannel(channelId: string | null) {
  store.selectedId = null
  const storageKey = channelStorageKey()
  if (storageKey) {
    if (channelId) localStorage.setItem(storageKey, channelId)
    else localStorage.removeItem(storageKey)
  }
  await store.loadConversations(channelId)
  if (store.selectedId) {
    await store.selectConversation(store.selectedId)
  }
}

async function sendMessage(
  text: string,
  replyToMessageId: string | null,
  mentionedPhones: string[],
  mentionedJids: string[],
  referencedContactIds: string[],
  done: (accepted: boolean) => void,
) {
  done(
    await store.send(
      text,
      replyToMessageId,
      mentionedPhones,
      mentionedJids,
      referencedContactIds,
    ),
  )
}

async function sendAttachment(
  files: File[],
  caption: string | null,
  replyToMessageId: string | null,
  mentionedPhones: string[],
  mentionedJids: string[],
  referencedContactIds: string[],
  done: (acceptedIndexes: number[]) => void,
) {
  done(
    await store.sendAttachments(
      files,
      caption,
      replyToMessageId,
      mentionedPhones,
      mentionedJids,
      referencedContactIds,
    ),
  )
}

async function sendContact(
  contact: ContactSearchResult,
  replyToMessageId: string | null,
  done: (accepted: boolean) => void,
) {
  done(await store.sendContact(contact, replyToMessageId))
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
  channels.value = await listChannels()
  const requestedConversationId =
    typeof route.query.conversation === 'string'
      ? route.query.conversation
      : null
  const requestedChannelId =
    typeof route.query.channel === 'string'
      ? route.query.channel
      : null
  const storedChannelId = channelStorageKey()
    ? localStorage.getItem(channelStorageKey() as string)
    : null
  const availableIds = new Set(channels.value.map((channel) => channel.id))
  const initialChannelId =
    requestedChannelId && availableIds.has(requestedChannelId)
      ? requestedChannelId
      : storedChannelId && availableIds.has(storedChannelId)
        ? storedChannelId
        : requestedConversationId && auth.user?.role === 'admin'
          ? null
          : channels.value[0]?.id || null
  await Promise.all([
    store.loadConversations(initialChannelId),
    auth.user?.role === 'admin'
      ? listUsers()
          .then((users) => {
            assignableUsers.value = users.filter((user) => user.is_active)
          })
          .catch(() => {
            assignableUsers.value = []
          })
      : Promise.resolve(),
  ])
  if (
    requestedConversationId &&
    store.conversations.some(
      (conversation) => conversation.id === requestedConversationId,
    )
  ) {
    await store.selectConversation(requestedConversationId)
  } else if (store.selectedId) {
    await store.selectConversation(store.selectedId)
  }
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
      :current-user-role="auth.user?.role || null"
      :assignable-users="assignableUsers"
      :channels="channels"
      :active-channel-id="store.activeChannelId"
      :can-view-all-channels="auth.user?.role === 'admin'"
      @select="store.selectConversation"
      @channel-change="selectChannel"
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
      :current-user-role="auth.user?.role || null"
      :assignable-users="assignableUsers"
      :sending="store.selectedSending"
      :send-error="store.selectedSendError"
      :operation-loading="store.operationLoading"
      :operation-error="store.operationError"
      :has-more-messages="store.hasMoreMessagesByConversation[store.selectedId || ''] ?? true"
      :loading-older-messages="store.loadingOlderMessages"
      @assign="store.assignSelected"
      @close="store.closeSelected"
      @send="sendMessage"
      @send-attachment="sendAttachment"
      @send-contact="sendContact"
      @retry="store.retryMessage"
      @read="store.markConversationRead"
      @back="backToConversationList"
      @show-contact="store.loadSelectedContact()"
      @refresh-contact="store.loadSelectedContact(true)"
      @load-older="store.selectedId && store.loadOlderMessages(store.selectedId)"
    />
  </div>
</template>
